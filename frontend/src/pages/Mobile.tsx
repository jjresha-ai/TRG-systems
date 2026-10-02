import { useEffect, useRef, useState } from 'react'
import { Camera, CloudOff, Crosshair, Mic, PhoneIncoming, Search, Star, WifiOff } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { ErrorBox, EntityLink, Field } from '@/components/common'
import { compactMoney, fmtDate } from '@/lib/utils'

interface Hit { type: string; id: number; title: string; subtitle: string }
interface QA { kind: string; record_type: string; record_id: number; text?: string; subject?: string; outcome?: string; client_id: string; label: string }
interface Prop { id: number; address: string; city: string; estimated_value: number | null; loan_maturity_date: string | null; distance_m?: number; owners: { company: string; principals: { name: string }[] }[] }
interface Caller { match: boolean; matches: { contact: { id: number; full_name: string; title: string | null; company: string | null; do_not_contact: boolean }; holdings: { property_id: number; address: string }[]; recent_activity: { subject: string; at: string }[]; recent_notes: { body: string }[] }[] }
interface StarT { record_type: string; record_id: number; label: string }

const QKEY = 'trg_quick_queue'
const readQueue = (): QA[] => { try { return JSON.parse(localStorage.getItem(QKEY) ?? '[]') } catch { return [] } }
const writeQueue = (q: QA[]) => { try { localStorage.setItem(QKEY, JSON.stringify(q)) } catch { /* storage unavailable */ } }
const urlFor = (t: string, id: number) => `/${t === 'company' ? 'companies' : t + 's'}/${id}`

type SR = { start: () => void; stop: () => void; onresult: ((e: { results: { 0: { transcript: string } }[] }) => void) | null; onend: (() => void) | null; lang: string; interimResults: boolean }
const Recognition = (): (new () => SR) | null => {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export default function Mobile() {
  const qc = useQueryClient()
  const [online, setOnline] = useState(navigator.onLine)
  const [queue, setQueue] = useState<QA[]>(readQueue)
  const [flash, setFlash] = useState('')
  useEffect(() => {
    const up = () => setOnline(true), down = () => setOnline(false)
    window.addEventListener('online', up); window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  const flush = async () => {
    let left = readQueue()
    for (const item of readQueue()) {
      try { const { label: _l, ...body } = item; void _l; await api('/quick-add', { method: 'POST', body }); left = left.filter((x) => x.client_id !== item.client_id) } catch (e) {
        if ((e as { status?: number }).status) left = left.filter((x) => x.client_id !== item.client_id)  // the server rejected it for good: do not retry forever
        else break  // still offline
      }
    }
    writeQueue(left); setQueue(left); qc.invalidateQueries()
  }
  useEffect(() => { if (online && readQueue().length) void flush() }, [online]) // eslint-disable-line react-hooks/exhaustive-deps
  const submit = async (qa: QA) => {
    try { await api('/quick-add', { method: 'POST', body: { ...qa, label: undefined } }); setFlash(`Saved to ${qa.label}`); qc.invalidateQueries() } catch (e) {
      if ((e as { status?: number }).status) throw e
      const q = [...readQueue(), qa]; writeQueue(q); setQueue(q); setFlash(`Offline: queued for ${qa.label}`)
    }
  }
  return (
    <div className="rise mx-auto max-w-xl">
      <PageHeader title="Field mode" subtitle="Quick capture from the car or the property. Works offline for starred records; adds sync when you're back." />
      <div className="mb-3 flex flex-wrap gap-2" data-testid="net-status">
        {online ? <Badge variant="success">Online</Badge> : <Badge variant="warning"><WifiOff className="h-3 w-3" /> Offline</Badge>}
        {queue.length > 0 && <Badge variant="accent" data-testid="queue-count"><CloudOff className="h-3 w-3" /> {queue.length} waiting to sync</Badge>}
        {queue.length > 0 && online && <Button size="sm" variant="outline" onClick={flush}>Sync now</Button>}
      </div>
      {flash && <div role="status" data-testid="flash" className="mb-3 rounded-md border border-success/30 bg-success/10 p-3 text-sm">{flash}</div>}
      <div className="grid gap-4">
        <QuickAdd onSubmit={submit} />
        <AddressLookup />
        <CallerLookup />
        <Starred />
      </div>
    </div>
  )
}

function RecordPicker({ value, onPick }: { value: Hit | null; onPick: (h: Hit | null) => void }) {
  const [q, setQ] = useState('')
  const res = useQuery({ queryKey: ['m-search', q], queryFn: () => api<{ results: Hit[] }>('/search', { params: { q, limit: 6 } }), enabled: q.length >= 2 && !value })
  if (value) return <div className="flex items-center gap-2 rounded-md border bg-muted px-3 py-2 text-sm"><span className="flex-1 font-medium" data-testid="picked">{value.title}</span><Button size="sm" variant="ghost" onClick={() => onPick(null)}>Change</Button></div>
  return (
    <div>
      <Input aria-label="Find a record" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Contact, owner entity or address…" />
      {res.data && <div className="mt-1 divide-y rounded-md border bg-card">{res.data.results.filter((r) => ['contact', 'company', 'property'].includes(r.type)).map((r) => (
        <button key={`${r.type}${r.id}`} className="block w-full px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => onPick(r)}><span className="font-medium">{r.title}</span> <span className="text-xs text-muted-foreground">{r.subtitle}</span></button>))}</div>}
    </div>
  )
}

function QuickAdd({ onSubmit }: { onSubmit: (qa: QA) => Promise<void> }) {
  const [rec, setRec] = useState<Hit | null>(null)
  const [kind, setKind] = useState('note')
  const [text, setText] = useState('')
  const [outcome, setOutcome] = useState('spoke')
  const [err, setErr] = useState('')
  const [listening, setListening] = useState(false)
  const R = Recognition()
  const dictate = () => {
    if (!R) return
    const r = new R(); r.lang = 'en-US'; r.interimResults = false
    r.onresult = (e) => setText((t) => `${t} ${e.results[0][0].transcript}`.trim()); r.onend = () => setListening(false)
    setListening(true); r.start()
  }
  const go = async () => {
    setErr('')
    if (!rec || !text.trim()) return setErr('Pick a record and add some text')
    const qa: QA = { kind, record_type: rec.type, record_id: rec.id, label: rec.title, client_id: `m-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, ...(kind === 'note' ? { text } : { subject: text, ...(kind === 'call_log' ? { outcome } : {}) }) }
    try { await onSubmit(qa); setText('') } catch (e) { setErr((e as Error).message) }
  }
  return (
    <Card><CardHeader><CardTitle>Quick add</CardTitle></CardHeader><CardContent className="grid gap-3">
      <RecordPicker value={rec} onPick={setRec} />
      <div className="flex gap-2">{[['note', 'Note'], ['task', 'Task'], ['call_log', 'Call log']].map(([k, l]) => <Button key={k} size="sm" variant={kind === k ? 'default' : 'outline'} onClick={() => setKind(k)}>{l}</Button>)}</div>
      <Field label={kind === 'note' ? 'Note' : kind === 'task' ? 'Task (due tomorrow)' : 'What was discussed'}>
        <div className="flex gap-2"><Input aria-label="Quick text" value={text} onChange={(e) => setText(e.target.value)} />
          {R && <Button variant={listening ? 'default' : 'outline'} aria-label="Dictate" onClick={dictate}><Mic className="h-4 w-4" /></Button>}</div></Field>
      {kind === 'call_log' && <Select aria-label="Call outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>{[['spoke', 'Spoke'], ['left_voicemail', 'Left voicemail'], ['no_answer', 'No answer']].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}
      {err && <ErrorBox error={new Error(err)} />}
      <Button onClick={go}>Save</Button>
      {rec && <PhotoButton rec={rec} />}
    </CardContent></Card>
  )
}

function PhotoButton({ rec }: { rec: Hit }) {
  const ref = useRef<HTMLInputElement>(null)
  const [msg, setMsg] = useState('')
  const up = async (f: File) => {
    const fd = new FormData(); fd.append('file', f); fd.append('record_type', rec.type); fd.append('record_id', String(rec.id)); fd.append('doc_type', 'photo'); fd.append('visibility', 'team')
    const res = await fetch('/api/documents', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${localStorage.getItem('trg_token')}` } })
    setMsg(res.ok ? 'Photo attached' : ((await res.json().catch(() => ({}))).detail ?? 'Upload failed'))
  }
  return (<div><input ref={ref} type="file" accept="image/*" capture="environment" aria-label="Take photo" className="hidden" onChange={(e) => e.target.files?.[0] && up(e.target.files[0])} />
    <Button variant="outline" className="w-full" onClick={() => ref.current?.click()}><Camera className="h-4 w-4" /> Photo of the property</Button>{msg && <p className="mt-1 text-xs text-muted-foreground" role="status">{msg}</p>}</div>)
}

function AddressLookup() {
  const [q, setQ] = useState('')
  const [geo, setGeo] = useState<{ lat: number; lng: number } | null>(null)
  const [err, setErr] = useState('')
  const res = useApi<{ items: Prop[] }>('/lookup/address', geo ? { lat: geo.lat, lng: geo.lng, radius_m: 300 } : { q }, { enabled: !!geo || q.length >= 2 })
  const locate = () => navigator.geolocation ? navigator.geolocation.getCurrentPosition((p) => { setErr(''); setGeo({ lat: p.coords.latitude, lng: p.coords.longitude }) }, () => setErr('Location unavailable')) : setErr('Location unavailable')
  return (
    <Card><CardHeader><CardTitle>Who owns this?</CardTitle></CardHeader><CardContent className="grid gap-3">
      <div className="flex gap-2"><div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input aria-label="Address lookup" className="pl-9" value={q} onChange={(e) => { setGeo(null); setQ(e.target.value) }} placeholder="Street address…" /></div>
        <Button variant="outline" aria-label="Use my location" onClick={locate}><Crosshair className="h-4 w-4" /></Button></div>
      {err && <ErrorBox error={new Error(err)} />}
      <div className="grid gap-2" data-testid="address-results">{res.data?.items.map((p) => (
        <div key={p.id} className="rounded-md border p-3 text-sm"><div className="flex items-center gap-2"><EntityLink to={`/properties/${p.id}`}>{p.address}, {p.city}</EntityLink>{p.distance_m != null && <Badge variant="secondary">{Math.round(p.distance_m)} m</Badge>}</div>
          {p.owners.map((o) => <div key={o.company} className="text-muted-foreground">{o.company}{o.principals[0] ? ` · ${o.principals[0].name}` : ''}</div>)}
          <div className="mt-1 flex gap-2 text-xs"><span>{compactMoney(p.estimated_value)}</span>{p.loan_maturity_date && <span>Loan matures {fmtDate(p.loan_maturity_date)}</span>}</div></div>))}</div>
    </CardContent></Card>
  )
}

function CallerLookup() {
  const [phone, setPhone] = useState('')
  const digits = phone.replace(/\D/g, '')
  const res = useApi<Caller>('/lookup/caller', { phone }, { enabled: digits.length >= 7 })
  return (
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><PhoneIncoming className="h-4 w-4" /> Who's calling?</CardTitle></CardHeader><CardContent className="grid gap-3">
      <Input aria-label="Caller phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(949) 555-0123" inputMode="tel" />
      <div data-testid="caller-result">
        {res.data && !res.data.match && <p className="text-sm text-muted-foreground">No match. Add them as a new contact after the call.</p>}
        {res.data?.matches.map((m) => (
          <div key={m.contact.id} className="rounded-md border p-3 text-sm"><div className="flex items-center gap-2"><EntityLink to={`/contacts/${m.contact.id}`}>{m.contact.full_name}</EntityLink>{m.contact.do_not_contact && <Badge variant="destructive">Do not contact</Badge>}</div>
            <div className="text-muted-foreground">{[m.contact.title, m.contact.company].filter(Boolean).join(' · ')}</div>
            {m.holdings.length > 0 && <div className="mt-1 text-xs">Owns: {m.holdings.map((h) => h.address).join('; ')}</div>}
            {m.recent_activity[0] && <div className="mt-1 text-xs">Last: {m.recent_activity[0].subject}</div>}
            {m.recent_notes[0] && <div className="mt-1 text-xs italic">“{m.recent_notes[0].body}”</div>}</div>))}
      </div>
    </CardContent></Card>
  )
}

function Starred() {
  const st = useApi<{ items: StarT[] }>('/stars')
  return (
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Star className="h-4 w-4" /> Starred (cached for offline)</CardTitle></CardHeader><CardContent>
      <div className="divide-y" data-testid="starred">{st.data?.items.map((s) => <div key={`${s.record_type}${s.record_id}`} className="flex items-center gap-2 py-2 text-sm"><Badge variant="secondary" className="capitalize">{s.record_type}</Badge><EntityLink to={urlFor(s.record_type, s.record_id)}>{s.label}</EntityLink></div>)}
        {st.data?.items.length === 0 && <p className="py-4 text-sm text-muted-foreground">Star contacts and properties to keep them handy offline.</p>}</div>
      {st.error && <ErrorBox error={st.error} />}
    </CardContent></Card>
  )
}
