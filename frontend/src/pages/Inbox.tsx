import { useState } from 'react'
import { Calendar, Inbox as InboxIcon, Lock, Mail, Send, ShieldOff, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ErrorBox, Field, Loading, Stat, EntityLink, Pagination } from '@/components/common'
import { fmtDate } from '@/lib/utils'

interface Conn { provider: string; email_address: string; can_send: boolean; bcc_token: string; planned_providers: string[]; last_synced_at: string | null }
interface Msg { id: number; direction: string; sent_at: string; from_addr: string; to_addrs: string[]; subject: string | null; body?: string; visibility: string; mine: boolean; owner: string | null; channel: string; associations: { record_type: string; record_id: number; auto: boolean }[] }
interface Ev { id: number; title: string; start_at: string; end_at: string; location: string | null; owner: string | null; mine: boolean; visibility: string; attendees: { email: string; name?: string }[] }
interface Summary { last_30_days: { inbound: number; outbound: number }; unlinked: number; private: number; shared: number; unsubscribed: number }
interface Rule { id: number; kind: string; value: string }
interface Tpl { id: number; name: string; subject: string; body: string }
interface Bulk { id: number; name: string; counts: Record<string, number>; created_at: string }

const LEVELS: [string, string][] = [['private', 'Only me'], ['team_metadata', 'Team sees who and when'], ['team_subject', 'Team sees subject'], ['team_full', 'Team sees everything']]
const LABEL = Object.fromEntries(LEVELS)
const rtPath = (t: string, id: number) => (t === 'contact' ? `/contacts/${id}` : t === 'property' ? `/properties/${id}` : t === 'deal' ? `/deals/${id}` : t === 'company' ? `/companies/${id}` : '/')

export default function Inbox() {
  const conn = useApi<Conn>('/email/connection')
  const sum = useApi<Summary>('/email/summary')
  return (
    <div className="rise">
      <PageHeader title="Email & Calendar" subtitle="Mail you choose to capture lands on the right contact timeline. Private by default; you decide what the team sees." />
      {conn.data && (
        <Card className="mb-4 border-accent/40 bg-accent/10"><CardContent className="flex flex-wrap items-center gap-3 pt-4 text-sm" data-testid="provider-notice">
          <Send className="h-4 w-4 text-[#7a5614]" />
          <div className="min-w-0 flex-1"><span className="font-semibold">Sending from the CRM is off until you choose Microsoft 365 or Google.</span> Capture works now: BCC <code className="rounded bg-muted px-1">{conn.data.bcc_token.slice(0, 8)}…</code> or sync. Bulk emails can be prepared and checked, not sent.</div>
          <Badge variant="secondary" className="capitalize">{conn.data.provider} · {conn.data.email_address}</Badge></CardContent></Card>
      )}
      {sum.data && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Inbound (30d)" value={sum.data.last_30_days.inbound} /><Stat label="Outbound (30d)" value={sum.data.last_30_days.outbound} />
          <Stat label="Needs a home" value={sum.data.unlinked} hint="Not matched to a contact" /><Stat label="Private" value={sum.data.private} hint={`${sum.data.shared} shared`} /><Stat label="Unsubscribed" value={sum.data.unsubscribed} />
        </div>
      )}
      <Tabs defaultValue="mail">
        <TabsList><TabsTrigger value="mail">Mail</TabsTrigger><TabsTrigger value="calendar">Calendar</TabsTrigger><TabsTrigger value="templates">Templates & bulk</TabsTrigger><TabsTrigger value="privacy">Privacy rules</TabsTrigger></TabsList>
        <TabsContent value="mail"><Mail_ /></TabsContent>
        <TabsContent value="calendar"><Cal /></TabsContent>
        <TabsContent value="templates"><Templates /></TabsContent>
        <TabsContent value="privacy"><Privacy /></TabsContent>
      </Tabs>
    </div>
  )
}

function Mail_() {
  const [page, setPage] = useState(1)
  const [unlinked, setUnlinked] = useState(false)
  const [q, setQ] = useState('')
  const msgs = useApi<Page<Msg>>('/email/messages', { page, limit: 15, unlinked: unlinked || undefined, q: q || undefined })
  const qc = useQueryClient()
  const share = useSend<{ id: number; level: string }>('POST', (b) => `/email/messages/${b.id}/share`, ['/email'])
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center gap-2">
        <CardTitle className="mr-auto flex items-center gap-2"><InboxIcon className="h-4 w-4" /> Captured mail</CardTitle>
        <Input aria-label="Search mail" className="w-56" placeholder="Search your mail…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <Button variant={unlinked ? 'default' : 'outline'} size="sm" onClick={() => { setUnlinked(!unlinked); setPage(1) }}>Needs a home</Button>
      </CardHeader>
      <CardContent className="p-0">
        {msgs.isLoading ? <Loading /> : msgs.error ? <ErrorBox error={msgs.error} /> : (
          <div className="divide-y" data-testid="mail-list">
            {msgs.data!.items.map((m) => (
              <div key={m.id} className="flex flex-wrap items-start gap-3 px-4 py-3" data-testid="mail-row">
                <div className="grid h-8 w-8 place-items-center rounded-full bg-primary/10 text-primary"><Mail className="h-4 w-4" /></div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-medium"><span className="truncate">{m.subject}</span><Badge variant="outline" className="capitalize">{m.direction}</Badge>
                    {m.channel === 'bcc' && <Badge variant="secondary">BCC</Badge>}</div>
                  <div className="text-xs text-muted-foreground">{m.direction === 'inbound' ? m.from_addr : m.to_addrs.join(', ')} · {fmtDate(m.sent_at)}</div>
                  {m.body && <div className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{m.body}</div>}
                  <div className="mt-1 flex flex-wrap gap-1.5">{m.associations.filter((a) => a.record_type !== 'contact' || true).slice(0, 4).map((a) => <EntityLink key={`${a.record_type}${a.record_id}`} to={rtPath(a.record_type, a.record_id)}><Badge variant="accent" className="capitalize">{a.record_type} #{a.record_id}</Badge></EntityLink>)}
                    {m.associations.length === 0 && <Badge variant="warning">Not linked to any record</Badge>}</div>
                </div>
                {m.mine && <Select aria-label={`Visibility for ${m.subject}`} value={m.visibility} onChange={(e) => share.mutate({ id: m.id, level: e.target.value }, { onSuccess: () => qc.invalidateQueries({ queryKey: ['/email/messages'] }) })}>
                  {LEVELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}
                {!m.mine && <Badge variant="secondary"><Lock className="h-3 w-3" /> {m.owner} · {LABEL[m.visibility]}</Badge>}
              </div>
            ))}
            {msgs.data!.items.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">Nothing here.</p>}
          </div>
        )}
        {msgs.data && <Pagination page={page} limit={15} total={msgs.data.total} onPage={setPage} />}
      </CardContent>
    </Card>
  )
}

function Cal() {
  const [{ start, end }] = useState(() => ({ start: new Date(Date.now() - 365 * 86400000).toISOString(), end: new Date(Date.now() + 30 * 86400000).toISOString() }))  // stable query key
  const ev = useApi<{ items: Ev[] }>('/calendar/events', { start, end })
  return (
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Calendar className="h-4 w-4" /> Meetings (past year, next 30 days)</CardTitle></CardHeader>
      <CardContent>{ev.isLoading ? <Loading /> : (
        <div className="divide-y" data-testid="event-list">{ev.data!.items.map((e) => (
          <div key={e.id} className="flex items-center gap-3 py-2.5 text-sm"><div className="w-28 text-xs text-muted-foreground">{fmtDate(e.start_at)}</div><div className="min-w-0 flex-1"><div className="font-medium">{e.title}</div>
            <div className="text-xs text-muted-foreground">{e.location ?? 'Location private'} · {e.mine ? 'You' : e.owner}</div></div>
            <Badge variant="outline">{e.attendees.length} attendees</Badge></div>))}
          {ev.data!.items.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">No meetings in range.</p>}</div>)}</CardContent></Card>
  )
}

function Templates() {
  const tpls = useApi<{ items: Tpl[] }>('/email/templates')
  const bulks = useApi<{ items: Bulk[] }>('/email/bulk')
  const lists = useApi<{ items: { id: number; name: string; entity: string }[] }>('/lists')
  const [sel, setSel] = useState<{ t: number; l: number; name: string }>({ t: 0, l: 0, name: '' })
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [result, setResult] = useState<Bulk | null>(null)
  const prepare = useSend<object, Bulk>('POST', '/email/bulk', ['/email/bulk'])
  const send = async (id: number) => {
    try { await api(`/email/bulk/${id}/send`, { method: 'POST' }); setMsg({ ok: true, text: 'Sent' }) } catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
  }
  const contactLists = lists.data?.items.filter((l) => l.entity === 'contact') ?? []
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Templates</CardTitle></CardHeader><CardContent className="grid gap-3">
        {tpls.data?.items.map((t) => <div key={t.id} className="rounded-md border p-3 text-sm" data-testid="template"><div className="font-medium">{t.name}</div><div className="text-xs text-muted-foreground">{t.subject}</div></div>)}
        <p className="text-xs text-muted-foreground">Merge fields: first_name, last_name, company, property_address, property_city, list_price, broker_name. Unknown fields are rejected.</p></CardContent></Card>
      <Card><CardHeader><CardTitle>Prepare a bulk email</CardTitle></CardHeader><CardContent className="grid gap-3">
        <Field label="Name"><Input aria-label="Bulk name" value={sel.name} onChange={(e) => setSel({ ...sel, name: e.target.value })} placeholder="Q4 owner outreach" /></Field>
        <Field label="Template"><Select className="w-full" aria-label="Bulk template" value={sel.t} onChange={(e) => setSel({ ...sel, t: Number(e.target.value) })}><option value={0}>Choose…</option>{tpls.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
        <Field label="Contact list"><Select className="w-full" aria-label="Bulk list" value={sel.l} onChange={(e) => setSel({ ...sel, l: Number(e.target.value) })}><option value={0}>Choose…</option>{contactLists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</Select></Field>
        <Button disabled={!sel.t || !sel.l || !sel.name || prepare.isPending} onClick={() => prepare.mutate({ name: sel.name, template_id: sel.t, list_id: sel.l }, { onSuccess: (r) => { setResult(r); setMsg(null) }, onError: (e) => setMsg({ ok: false, text: (e as Error).message }) })}>Prepare and check recipients</Button>
        {result && <div className="rounded-md bg-muted p-3 text-sm" data-testid="bulk-result">Eligible <b>{result.counts.eligible}</b> · Do-not-contact removed <b>{result.counts.excluded_dnc}</b> · Unsubscribed removed <b>{result.counts.excluded_unsubscribed}</b> · No email <b>{result.counts.no_email}</b></div>}
        {result && <Button variant="outline" onClick={() => send(result.id)}><Send className="h-4 w-4" /> Send</Button>}
        {msg && (msg.ok ? <p className="text-sm">{msg.text}</p> : <div role="alert" data-testid="send-blocked" className="rounded-md border border-accent/40 bg-accent/10 p-3 text-sm">{msg.text}</div>)}
      </CardContent></Card>
      <Card className="lg:col-span-2"><CardHeader><CardTitle>Prepared sends</CardTitle></CardHeader><CardContent className="divide-y">
        {bulks.data?.items.map((b) => <div key={b.id} className="flex items-center gap-3 py-2 text-sm" data-testid="bulk-row"><span className="min-w-0 flex-1 font-medium">{b.name}</span><Badge variant="success">{b.counts.eligible} eligible</Badge><Badge variant="destructive">{b.counts.excluded_dnc} DNC</Badge><Badge variant="warning">{b.counts.excluded_unsubscribed} unsub</Badge></div>)}</CardContent></Card>
    </div>
  )
}

function Privacy() {
  const rules = useApi<{ items: Rule[] }>('/email/exclusions')
  const [f, setF] = useState({ kind: 'domain', value: '' })
  const [err, setErr] = useState('')
  const add = useSend<object>('POST', '/email/exclusions', ['/email/exclusions'])
  const del = useSend<number>('DELETE', (id) => `/email/exclusions/${id}`, ['/email/exclusions'])
  return (
    <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldOff className="h-4 w-4" /> Never capture</CardTitle></CardHeader><CardContent className="grid gap-3">
      <p className="text-sm text-muted-foreground">Mail matching these rules is dropped before it is stored. Family, medical and anything personal stays out of the CRM.</p>
      <div className="flex flex-wrap items-end gap-2">
        <Select aria-label="Rule kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="domain">Domain</option><option value="address">Address</option><option value="keyword">Keyword</option></Select>
        <Input aria-label="Rule value" className="w-64" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} placeholder="family.example or divorce" />
        <Button onClick={() => add.mutate(f, { onSuccess: () => { setF({ ...f, value: '' }); setErr('') }, onError: (e) => setErr((e as Error).message) })}>Add rule</Button></div>
      {err && <ErrorBox error={new Error(err)} />}
      <div className="divide-y" data-testid="rules">{rules.data?.items.map((r) => <div key={r.id} className="flex items-center gap-3 py-2 text-sm"><Badge variant="secondary" className="capitalize">{r.kind}</Badge><span className="flex-1">{r.value}</span>
        <Button size="sm" variant="ghost" aria-label={`Remove ${r.value}`} onClick={() => del.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button></div>)}</div>
    </CardContent></Card>
  )
}
