import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Calendar, CheckCircle2, Download, FileText, Footprints, Lock, Mail, MessageSquare, Phone, Pin, Plus, Repeat, StickyNote, Users, Upload } from 'lucide-react'
import { api } from '@/api/client'
import { useApi, useSend } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading } from '@/components/common'
import { cn, fmtDate } from '@/lib/utils'

export interface Act {
  id: number; type: string; subject: string; body: string | null; status: string; due_at: string | null; completed_at: string | null; assignee: string | null
  priority: string; outcome: string | null; overdue: boolean; recurrence_days: number | null; associations: { record_type: string; record_id: number; label: string }[]
}
interface NoteT { id: number; body: string; author: string; pinned: boolean; visibility: string; version: number; edited: boolean; created_at: string }
interface DocT { id: number; file_name: string; doc_type: string; size: number; visibility: string; version: number; versions: number; uploader: string; uploaded_at: string }
interface TL { upcoming: { kind: string; at: string; data: Act }[]; history: { kind: string; at: string; data: Act & NoteT & DocT }[]; pinned: unknown[] }

export const TYPE_ICON: Record<string, typeof Phone> = { call: Phone, email: Mail, meeting: Users, site_visit: Footprints, text: MessageSquare, other: Calendar }
export const OUTCOMES = [['spoke', 'Spoke'], ['left_voicemail', 'Left voicemail'], ['no_answer', 'No answer'], ['not_interested', 'Not interested'], ['meeting_set', 'Meeting set']]

export function CompleteDialog({ act, onClose, onDone }: { act: Act | null; onClose: () => void; onDone: () => void }) {
  const [outcome, setOutcome] = useState('spoke')
  const [body, setBody] = useState('')
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', `/activities/${act?.id}/complete`)
  return (
    <Dialog open={!!act} onOpenChange={(o) => { if (!o) { onClose(); setErr('') } }}>
      <DialogContent>{act && (<>
        <DialogTitle>Complete: {act.subject}</DialogTitle>
        <DialogDescription>Completing a task logs it as an activity and updates last-contact dates.</DialogDescription>
        <div className="mt-4 grid gap-3">
          {act.type === 'call' && <Field label="Outcome"><Select className="w-full" aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>{OUTCOMES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>}
          <Field label="Notes"><Input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Optional" /></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={m.isPending} onClick={() => m.mutate({ outcome: act.type === 'call' ? outcome : undefined, body: body || undefined }, { onSuccess: () => { onDone(); onClose(); setBody('') }, onError: (e) => setErr((e as Error).message) })}>Mark complete</Button>
        </div>
      </>)}</DialogContent>
    </Dialog>
  )
}

export function ActivityRow({ a, onComplete }: { a: Act; onComplete?: (a: Act) => void }) {
  const I = TYPE_ICON[a.type] ?? Calendar
  const planned = a.status === 'planned'
  return (
    <div className="flex items-start gap-3 py-2.5" data-testid={planned ? 'task-row' : 'activity-row'}>
      <div className={cn('mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full', planned ? (a.overdue ? 'bg-destructive/12 text-destructive' : 'bg-accent/20 text-[#7a5614]') : 'bg-muted text-muted-foreground')}><I className="h-4 w-4" /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{a.subject}</span>
          {a.priority === 'high' && planned && <Badge variant="destructive">High</Badge>}{a.recurrence_days && <Badge variant="outline"><Repeat className="h-3 w-3" /> every {a.recurrence_days}d</Badge>}
          {a.outcome && <Badge variant="secondary" className="capitalize">{a.outcome.replace('_', ' ')}</Badge>}</div>
        <div className="text-xs text-muted-foreground">{planned ? <span className={cn(a.overdue && 'font-semibold text-destructive')}>{a.overdue ? 'Overdue · ' : 'Due '}{fmtDate(a.due_at)}</span> : fmtDate(a.completed_at)} · {a.assignee}
          {a.associations.length > 1 && ` · ${a.associations.filter((x) => x.record_type !== 'contact').map((x) => x.label).slice(0, 2).join(', ')}`}</div>
        {a.body && <div className="mt-0.5 text-sm text-muted-foreground">{a.body}</div>}
      </div>
      {planned && onComplete && <Button size="sm" variant="outline" onClick={() => onComplete(a)} aria-label={`Complete ${a.subject}`}><CheckCircle2 className="h-4 w-4" /> Done</Button>}
    </div>
  )
}

export function ActivityPanel({ recordType, recordId }: { recordType: string; recordId: number }) {
  const qc = useQueryClient()
  const tl = useApi<TL>('/timeline', { record_type: recordType, record_id: recordId })
  const [done, setDone] = useState<Act | null>(null)
  const refresh = () => qc.invalidateQueries()
  const notes = tl.data?.history.filter((h) => h.kind === 'note') ?? []
  const docs = tl.data?.history.filter((h) => h.kind === 'document') ?? []
  return (
    <Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><CardTitle>Activity</CardTitle>
      <div className="flex gap-2"><LogActivity recordType={recordType} recordId={recordId} onDone={refresh} /><AddNote recordType={recordType} recordId={recordId} onDone={refresh} /><UploadDoc recordType={recordType} recordId={recordId} onDone={refresh} /><ApplyCadence recordType={recordType} recordId={recordId} onDone={refresh} /></div></div></CardHeader>
      <CardContent>
        {tl.isLoading ? <Loading /> : (
          <Tabs defaultValue="timeline">
            <TabsList><TabsTrigger value="timeline">Timeline</TabsTrigger><TabsTrigger value="notes">Notes ({notes.length})</TabsTrigger><TabsTrigger value="docs">Documents ({docs.length})</TabsTrigger></TabsList>
            <TabsContent value="timeline">
              {(tl.data?.upcoming.length ?? 0) > 0 && (<div className="mb-3 rounded-lg border bg-accent/5 px-3"><div className="pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Upcoming</div>
                <div className="divide-y">{tl.data!.upcoming.map((u) => <ActivityRow key={u.data.id} a={u.data} onComplete={setDone} />)}</div></div>)}
              <div className="divide-y">{tl.data?.history.map((h) => h.kind === 'activity' ? <ActivityRow key={`a${h.data.id}`} a={h.data} /> : h.kind === 'note' ? <NoteRow key={`n${h.data.id}`} n={h.data} /> : <DocRow key={`d${h.data.id}`} d={h.data} />)}</div>
              {tl.data && tl.data.history.length + tl.data.upcoming.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No activity yet. Log a call or apply a cadence to start the timeline.</p>}
            </TabsContent>
            <TabsContent value="notes"><div className="divide-y">{notes.map((h) => <NoteRow key={h.data.id} n={h.data} />)}{notes.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No notes.</p>}</div></TabsContent>
            <TabsContent value="docs"><div className="divide-y">{docs.map((h) => <DocRow key={h.data.id} d={h.data} />)}{docs.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No documents.</p>}</div></TabsContent>
          </Tabs>)}
        <CompleteDialog act={done} onClose={() => setDone(null)} onDone={refresh} />
      </CardContent></Card>
  )
}

function NoteRow({ n }: { n: NoteT }) {
  return (
    <div className="flex items-start gap-3 py-2.5" data-testid="note-row"><div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/20 text-[#7a5614]"><StickyNote className="h-4 w-4" /></div>
      <div className="min-w-0 flex-1"><div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="font-medium text-foreground">{n.author}</span>{fmtDate(n.created_at)}{n.edited && <span>(edited)</span>}
        {n.pinned && <Pin className="h-3 w-3 text-accent" />}{n.visibility === 'private' && <Badge variant="outline"><Lock className="h-3 w-3" /> Private</Badge>}</div><p className="mt-0.5 text-sm">{n.body}</p></div></div>
  )
}

function DocRow({ d }: { d: DocT }) {
  const open = async () => { const r = await api<{ url: string }>(`/documents/${d.id}/url`, { method: 'POST' }); window.open(r.url, '_blank') }
  return (
    <div className="flex items-center gap-3 py-2.5" data-testid="doc-row"><div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary"><FileText className="h-4 w-4" /></div>
      <div className="min-w-0 flex-1"><div className="flex items-center gap-2 text-sm font-medium"><span className="truncate">{d.file_name}</span><Badge variant="secondary" className="uppercase">{d.doc_type.replace('_', ' ')}</Badge>
        {d.versions > 1 && <Badge variant="outline">v{d.version} of {d.versions}</Badge>}{d.visibility === 'confidential' && <Badge variant="destructive"><Lock className="h-3 w-3" /> Confidential</Badge>}</div>
        <div className="text-xs text-muted-foreground">{(d.size / 1024).toFixed(0)} KB · {d.uploader} · {fmtDate(d.uploaded_at)}</div></div>
      <Button size="sm" variant="ghost" aria-label={`Download ${d.file_name}`} onClick={open}><Download className="h-4 w-4" /></Button></div>
  )
}

function LogActivity({ recordType, recordId, onDone }: { recordType: string; recordId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ type: 'call', subject: '', mode: 'done', due: '', outcome: 'spoke', recurrence: '' })
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', '/activities')
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Plus className="h-4 w-4" /> Log / task</Button></DialogTrigger>
      <DialogContent><DialogTitle>Log activity or create task</DialogTitle><DialogDescription>Tasks and logged activity are one record: completing a task logs it.</DialogDescription>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Field label="Type"><Select className="w-full" aria-label="Activity type" value={f.type} onChange={set('type')}>{['call', 'email', 'meeting', 'site_visit', 'text', 'other'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</Select></Field>
          <Field label="When"><Select className="w-full" aria-label="When" value={f.mode} onChange={set('mode')}><option value="done">Already happened</option><option value="planned">Schedule a task</option></Select></Field>
          <Field label="Subject" className="col-span-2"><Input aria-label="Subject" value={f.subject} onChange={set('subject')} /></Field>
          {f.mode === 'planned' ? (<>
            <Field label="Due"><Input type="datetime-local" aria-label="Due" value={f.due} onChange={set('due')} /></Field>
            <Field label="Repeat every (days)"><Input type="number" aria-label="Repeat days" value={f.recurrence} onChange={set('recurrence')} placeholder="e.g. 90" /></Field>
          </>) : f.type === 'call' ? <Field label="Outcome" className="col-span-2"><Select className="w-full" aria-label="Call outcome" value={f.outcome} onChange={set('outcome')}>{OUTCOMES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field> : null}
          {err && <div className="col-span-2"><ErrorBox error={new Error(err)} /></div>}
          <Button className="col-span-2" disabled={m.isPending || !f.subject} onClick={() => m.mutate({
            type: f.type, subject: f.subject, status: f.mode === 'done' ? 'completed' : 'planned', due_at: f.mode === 'planned' ? f.due || undefined : undefined,
            outcome: f.mode === 'done' && f.type === 'call' ? f.outcome : undefined, recurrence_days: f.recurrence ? Number(f.recurrence) : undefined, associations: [{ record_type: recordType, record_id: recordId }],
          }, { onSuccess: () => { onDone(); setOpen(false); setF({ ...f, subject: '' }) }, onError: (e) => setErr((e as Error).message) })}>Save</Button>
        </div></DialogContent>
    </Dialog>
  )
}

function AddNote({ recordType, recordId, onDone }: { recordType: string; recordId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState('')
  const [priv, setPriv] = useState(false)
  const [pin, setPin] = useState(false)
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', '/notes')
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><StickyNote className="h-4 w-4" /> Note</Button></DialogTrigger>
      <DialogContent><DialogTitle>Add note</DialogTitle><DialogDescription>Use @[Name] to mention a teammate. Keep structured facts (hold intent, pricing, loan maturity) in fields, not notes.</DialogDescription>
        <div className="mt-4 grid gap-3">
          <textarea aria-label="Note" value={body} onChange={(e) => setBody(e.target.value)} rows={5} className="w-full rounded-md border border-input bg-card p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          <div className="flex gap-4 text-sm"><label className="flex items-center gap-2"><input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} /> Private (only me)</label><label className="flex items-center gap-2"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> Pin</label></div>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={m.isPending || !body.trim()} onClick={() => m.mutate({ body, visibility: priv ? 'private' : 'team', pinned: pin, associations: [{ record_type: recordType, record_id: recordId }] }, { onSuccess: () => { onDone(); setOpen(false); setBody('') }, onError: (e) => setErr((e as Error).message) })}>Save note</Button>
        </div></DialogContent>
    </Dialog>
  )
}

function UploadDoc({ recordType, recordId, onDone }: { recordType: string; recordId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState('other')
  const [conf, setConf] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const submit = async () => {
    const f = file.current?.files?.[0]
    if (!f) return setErr('Choose a file')
    setBusy(true); setErr('')
    const fd = new FormData()
    fd.append('file', f); fd.append('record_type', recordType); fd.append('record_id', String(recordId)); fd.append('doc_type', type); fd.append('visibility', conf ? 'confidential' : 'team')
    const res = await fetch('/api/documents', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${localStorage.getItem('trg_token')}` } })
    setBusy(false)
    if (!res.ok) { const j = await res.json().catch(() => ({})); return setErr(j.detail ?? res.statusText) }
    onDone(); setOpen(false)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Upload className="h-4 w-4" /> Document</Button></DialogTrigger>
      <DialogContent><DialogTitle>Upload document</DialogTitle><DialogDescription>Same file name on the same record becomes a new version. PDF, Office, image, CSV or text up to 10 MB.</DialogDescription>
        <div className="mt-4 grid gap-3">
          <input ref={file} type="file" aria-label="File" className="text-sm" />
          <Field label="Type"><Select className="w-full" aria-label="Document type" value={type} onChange={(e) => setType(e.target.value)}>{['om', 'ca', 'loi', 'psa', 'rent_roll', 'flyer', 'photo', 'other'].map((t) => <option key={t} value={t}>{t.replace('_', ' ').toUpperCase()}</option>)}</Select></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={conf} onChange={(e) => setConf(e.target.checked)} /> Confidential (downloads are audited)</label>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={busy} onClick={submit}>Upload</Button>
        </div></DialogContent>
    </Dialog>
  )
}

function ApplyCadence({ recordType, recordId, onDone }: { recordType: string; recordId: number; onDone: () => void }) {
  const { data } = useApi<{ id: number; name: string; record_type: string }[]>('/cadences')
  const m = useSend<{ id: number }, { created: number }>('POST', (b) => `/cadences/${b.id}/apply`)
  const [msg, setMsg] = useState('')
  const options = data?.filter((c) => c.record_type === recordType || c.record_type === 'any') ?? []
  if (options.length === 0) return null
  return (
    <div className="flex items-center gap-2">
      <Select aria-label="Apply cadence" value="" className="h-8 text-xs" onChange={(e) => {
        const id = Number(e.target.value); if (!id) return
        api<{ created: number }>(`/cadences/${id}/apply`, { method: 'POST', body: { record_type: recordType, record_id: recordId } }).then((r) => { setMsg(r.created ? `${r.created} tasks created` : 'Already applied today'); onDone() }).catch((er) => setMsg((er as Error).message))
        void m
      }}><option value="">Apply cadence…</option>{options.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
      {msg && <span className="text-xs text-success">{msg}</span>}
    </div>
  )
}
