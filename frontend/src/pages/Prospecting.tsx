import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Play, Flame } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { EntityLink, ErrorBox, Loading, Stat, ago } from '@/components/common'
import { compactMoney, cn, fmtDate } from '@/lib/utils'

export interface Lead {
  id: number; name: string; company_name: string | null; status: string; source: string | null; score: number; score_components: Record<string, number>
  owner_name: string | null; property_id: number | null; contact_id: number | null; company_id: number | null; created_at: string; notes: string | null
  property: { address: string; city: string; property_type: string; estimated_value: number | null; loan_maturity_date: string | null; hold_intent: string } | null
  trigger_reason: { matches: { rule: string; kind: string; detail: string }[] } | null; disqualify_reason: string | null; deal_id: number | null; email: string | null; phone: string | null
}
interface Stats { by_status: Record<string, number>; total: number; by_source: { source_id: number; source: string; leads: number; converted: number; conversion_rate: number }[] }
interface Rule { id: number; name: string; kind: string; threshold: number; property_type: string | null; enabled: boolean }
interface JobInfo { name: string; description: string; last_run: { status: string; finished_at: string; summary: Record<string, number> } | null }
interface Camp { id: number; name: string; description: string; leads: number; converted: number; started_on: string }

const COLS = [['new', 'New'], ['contacted', 'Contacted'], ['qualified', 'Qualified'], ['converted', 'Converted']] as const

export function ScoreDial({ score }: { score: number }) {
  const hot = score >= 60
  return (
    <div className={cn('grid h-11 w-11 shrink-0 place-items-center rounded-full border-2 font-display text-base font-semibold', hot ? 'border-accent bg-accent/15 text-[#7a5614]' : 'border-border bg-muted text-muted-foreground')} title={`Score ${score}`}>{score}</div>
  )
}

export default function Prospecting() {
  const stats = useApi<Stats>('/leads/stats')
  const [open, setOpen] = useState<Lead | null>(null)
  return (
    <div className="rise">
      <PageHeader title="Owner Prospecting" subtitle="Hold/sell triggers surface owners to call. Scores are transparent and additive." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {COLS.map(([k, label]) => <Stat key={k} label={label} value={stats.data?.by_status[k] ?? '—'} />)}
        <Stat label="Conversion" value={stats.data ? `${Math.round(((stats.data.by_status.converted ?? 0) / Math.max(stats.data.total - (stats.data.by_status.new ?? 0), 1)) * 100)}%` : '—'} hint="converted / worked leads" />
      </div>
      <Tabs defaultValue="board">
        <TabsList><TabsTrigger value="board">Lead board</TabsTrigger><TabsTrigger value="triggers">Triggers & rules</TabsTrigger><TabsTrigger value="sources">Sources & campaigns</TabsTrigger></TabsList>
        <TabsContent value="board"><Board onOpen={setOpen} /></TabsContent>
        <TabsContent value="triggers"><Triggers /></TabsContent>
        <TabsContent value="sources"><Sources stats={stats.data} /></TabsContent>
      </Tabs>
      <LeadDialog lead={open} onClose={() => setOpen(null)} />
    </div>
  )
}

function Board({ onOpen }: { onOpen: (l: Lead) => void }) {
  return (
    <div className="grid gap-4 lg:grid-cols-4">
      {COLS.map(([k, label]) => <Column key={k} status={k} label={label} onOpen={onOpen} />)}
    </div>
  )
}

function Column({ status, label, onOpen }: { status: string; label: string; onOpen: (l: Lead) => void }) {
  const { data, isLoading } = useApi<Page<Lead>>('/leads', { status, limit: 10, sort: 'score' })
  return (
    <div className="rounded-xl bg-muted/60 p-3" data-testid={`col-${status}`}>
      <div className="mb-2 flex items-center justify-between px-1"><h3 className="font-display text-base font-semibold">{label}</h3><Badge variant="outline">{data?.total ?? '…'}</Badge></div>
      <div className="space-y-2">
        {isLoading && <Loading />}
        {data?.items.map((l) => (
          <button key={l.id} onClick={() => onOpen(l)} className="flex w-full cursor-pointer items-start gap-3 rounded-lg border bg-card p-3 text-left transition-shadow hover:shadow-md">
            <ScoreDial score={l.score} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{l.name}</div>
              <div className="truncate text-xs text-muted-foreground">{l.property ? `${l.property.address}, ${l.property.city}` : l.company_name ?? 'No property linked'}</div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {l.trigger_reason?.matches.slice(0, 2).map((m, i) => <Badge key={i} variant="warning" className="max-w-full truncate">{m.rule}</Badge>)}
                {!l.trigger_reason && l.source && <Badge variant="outline">{l.source}</Badge>}
              </div>
            </div>
          </button>
        ))}
        {data && data.total > data.items.length && <p className="px-1 pt-1 text-xs text-muted-foreground">+ {data.total - data.items.length} more, highest scores first</p>}
      </div>
    </div>
  )
}

function LeadDialog({ lead, onClose }: { lead: Lead | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('Not selling')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const done = () => { qc.invalidateQueries(); onClose(); setMsg('') }
  const patch = useSend<{ id: number; body: object }>('PATCH', (b) => `/leads/${b.id}`)
  const convert = useSend<{ id: number }, { contact_id: number }>('POST', (b) => `/leads/${b.id}/convert`)
  const set = (status: string, extra: object = {}) => lead && patch.mutate({ id: lead.id, body: { status, ...extra } } as never, { onSuccess: done, onError: (e) => setErr((e as Error).message) })
  const total = lead ? Object.values(lead.score_components).reduce((a, b) => a + b, 0) : 0
  return (
    <Dialog open={!!lead} onOpenChange={(o) => { if (!o) { onClose(); setErr('') } }}>
      <DialogContent className="max-w-xl">
        {lead && (<>
          <DialogTitle>{lead.name}</DialogTitle>
          <DialogDescription>{lead.property ? `${lead.property.address}, ${lead.property.city} · ${compactMoney(lead.property.estimated_value)}` : 'No property linked'} · {lead.source} · {ago(lead.created_at)}</DialogDescription>
          <div className="mt-4 flex items-center gap-4"><ScoreDial score={lead.score} /><div><div className="text-sm font-semibold">Why this score</div><div className="text-xs text-muted-foreground">Additive rules, stored with the lead</div></div></div>
          <div className="mt-2 space-y-1.5">
            {Object.entries(lead.score_components).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-sm"><span className="w-32 capitalize text-muted-foreground">{k}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-muted"><div className="h-full bg-accent" style={{ width: `${(v / Math.max(total, 1)) * 100}%` }} /></div><span className="w-8 text-right tabular-nums">+{v}</span></div>))}
          </div>
          {lead.trigger_reason && (<div className="mt-4 rounded-lg border bg-background p-3"><div className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><Flame className="h-4 w-4 text-accent" /> Triggered by</div>
            <ul className="space-y-1 text-sm">{lead.trigger_reason.matches.map((m, i) => <li key={i}><span className="font-medium">{m.rule}:</span> <span className="text-muted-foreground">{m.detail}</span></li>)}</ul></div>)}
          <div className="mt-3 flex flex-wrap gap-3 text-sm">
            {lead.property_id && <EntityLink to={`/properties/${lead.property_id}`}>View property</EntityLink>}
            {lead.contact_id && <EntityLink to={`/contacts/${lead.contact_id}`}>View contact</EntityLink>}
          </div>
          {lead.status === 'disqualified' && <p className="mt-3 text-sm text-destructive">Disqualified: {lead.disqualify_reason}</p>}
          {err && <div className="mt-3"><ErrorBox error={new Error(err)} /></div>}
          {msg && <p className="mt-3 text-sm text-success">{msg}</p>}
          {!['converted', 'disqualified'].includes(lead.status) && (
            <div className="mt-5 flex flex-wrap items-center gap-2 border-t pt-4">
              {lead.status === 'new' && <Button size="sm" variant="outline" onClick={() => set('contacted')}>Mark contacted</Button>}
              {lead.status !== 'qualified' && <Button size="sm" variant="outline" onClick={() => set('qualified')}>Mark qualified</Button>}
              <Button size="sm" variant="accent" onClick={() => convert.mutate({ id: lead.id }, { onSuccess: done, onError: (e) => setErr((e as Error).message) })}>Convert to contact</Button>
              <div className="ml-auto flex items-center gap-1">
                <Select aria-label="Disqualify reason" value={reason} onChange={(e) => setReason(e.target.value)} className="h-8 text-xs">{['Not selling', 'Listed elsewhere', 'Wrong decision-maker', 'Unresponsive'].map((r) => <option key={r}>{r}</option>)}</Select>
                <Button size="sm" variant="ghost" onClick={() => set('disqualified', { disqualify_reason: reason })}>Disqualify</Button>
              </div>
            </div>)}
        </>)}
      </DialogContent>
    </Dialog>
  )
}

function Triggers() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const rules = useApi<Rule[]>('/trigger-rules')
  const jobs = useApi<JobInfo[]>('/jobs')
  const run = useSend<null, { status: string; summary: Record<string, number> }>('POST', '/jobs/hold_sell_triggers/run')
  const toggle = useSend<{ id: number; enabled: boolean }>('PATCH', (b) => `/trigger-rules/${b.id}`)
  const assign = useApi<{ id: number; name: string; strategy: string; users: string[]; property_type: string | null }[]>('/assignment-rules')
  const job = jobs.data?.find((j) => j.name === 'hold_sell_triggers')
  const [result, setResult] = useState('')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Hold/sell trigger rules</CardTitle></CardHeader><CardContent>
        <ul className="divide-y">{rules.data?.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-2.5 text-sm"><div><div className="font-medium">{r.name}</div><div className="text-xs capitalize text-muted-foreground">{r.kind.replace('_', ' ')} · threshold {r.threshold}{r.property_type ? ` · ${r.property_type} only` : ''}</div></div>
            <Button size="sm" variant={r.enabled ? 'default' : 'outline'} disabled={user?.role !== 'admin' && user?.role !== 'manager'}
              onClick={() => toggle.mutate({ id: r.id, enabled: !r.enabled }, { onSuccess: () => qc.invalidateQueries() })}>{r.enabled ? 'On' : 'Off'}</Button></li>))}
        </ul>
        <div className="mt-4 flex items-center gap-3 border-t pt-4">
          <Button variant="accent" disabled={user?.role !== 'admin' || run.isPending} onClick={() => run.mutate(null, { onSuccess: (r) => { setResult(`Created ${r.summary.leads_created} leads, ${r.summary.reasons_added} added reasons, ${r.summary.already_handled} already handled.`); qc.invalidateQueries() } })}>
            <Play className="h-4 w-4" /> Run triggers now
          </Button>
          {user?.role !== 'admin' && <span className="text-xs text-muted-foreground">Admin only</span>}
        </div>
        {result && <p className="mt-3 text-sm text-success">{result}</p>}
        {job?.last_run && <p className="mt-2 text-xs text-muted-foreground">Last run: {job.last_run.status} · {fmtDate(job.last_run.finished_at)}</p>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Lead assignment</CardTitle></CardHeader><CardContent>
        <ul className="divide-y text-sm">{assign.data?.map((a) => (<li key={a.id} className="py-2.5"><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground">{a.strategy.replace('_', ' ')} → {a.users.join(', ')}</div></li>))}</ul>
        <p className="mt-3 text-xs text-muted-foreground">No matching rule? Leads round-robin across brokers.</p>
      </CardContent></Card>
    </div>
  )
}

function Sources({ stats }: { stats?: Stats }) {
  const camps = useApi<Camp[]>('/campaigns')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Lead sources</CardTitle></CardHeader><CardContent className="px-0">
        <Table><THead><TR><TH>Source</TH><TH className="text-right">Leads</TH><TH className="text-right">Converted</TH><TH className="text-right">Rate</TH></TR></THead>
          <TBody>{stats?.by_source.filter((s) => s.leads > 0).sort((a, b) => b.leads - a.leads).map((s) => (<TR key={s.source_id}><TD>{s.source}</TD><TD className="text-right tabular-nums">{s.leads}</TD><TD className="text-right tabular-nums">{s.converted}</TD><TD className="text-right tabular-nums">{s.conversion_rate}%</TD></TR>))}</TBody></Table>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Campaigns</CardTitle></CardHeader><CardContent><ul className="divide-y text-sm">{camps.data?.map((c) => (
        <li key={c.id} className="py-2.5"><div className="flex justify-between font-medium"><span>{c.name}</span><span className="tabular-nums text-muted-foreground">{c.leads} leads · {c.converted} won</span></div><div className="text-xs text-muted-foreground">{c.description}</div></li>))}</ul></CardContent></Card>
    </div>
  )
}
