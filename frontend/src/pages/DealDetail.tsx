import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Pencil } from 'lucide-react'
import { useApi, useSend, useUsers } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EntityLink, ErrorBox, Loading, Stat } from '@/components/common'
import { StageMoveDialog, needs, type DealLite, type StageLite } from '@/components/StageMove'
import { compactMoney, cn, fmtDate, money } from '@/lib/utils'
import { ActivityPanel } from '@/components/ActivityPanel'
import { CustomFieldsCard } from '@/components/CustomFieldsCard'

interface Detail extends DealLite {
  pipeline: { id: number; key: string; name: string }; status: string; probability: number; owner_name: string | null; property_id: number | null; listing_id: number | null
  property: { address: string; city: string; property_type: string } | null; expected_close_date: string | null; actual_close_date: string | null; listing_expiration_date: string | null
  loan_contingency_date: string | null; days_in_stage: number; rotting: boolean; gross_commission?: number | null; commission_rate_bps?: number | null; weighted_commission?: number | null
  parties: { id: number; role: string; contact_id: number | null; company_id: number | null; contact: string | null; company: string | null }[]
  splits?: { id: number; recipient_user_id: number | null; external_name: string | null; kind: string; split_type: string; pct: number | null; amount: number | null }[]
  history: { id: number; stage: string; from: string | null; at: string; user: string | null; note: string | null; days: number }[]
  source: string | null
}
interface Pipe { key: string; stages: (StageLite & { position: number; probability: number })[] }

export default function DealDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: d, isLoading, error } = useApi<Detail>(`/deals/${id}`)
  const pipes = useApi<Pipe[]>('/pipelines')
  const [to, setTo] = useState<StageLite | null>(null)
  const [err, setErr] = useState('')
  const quick = useSend<{ stage_id: number }>('POST', `/deals/${id}/stage`)
  if (isLoading) return <Loading />
  if (error || !d) return <ErrorBox error={error} />
  const stages = pipes.data?.find((p) => p.key === d.pipeline.key)?.stages ?? []
  const open = stages.filter((s) => !s.is_won && !s.is_lost)
  const cur = stages.find((s) => s.id === d.stage.id)
  const refresh = () => qc.invalidateQueries()
  const go = (s: StageLite) => {
    setErr('')
    const n = needs(d, s)
    if (n.price || n.lost || n.dd) return setTo(s)
    quick.mutate({ stage_id: s.id }, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) })
  }
  return (
    <div className="rise">
      <PageHeader title={d.name} subtitle={`${d.pipeline.name} · owner ${d.owner_name ?? '—'}${d.source ? ' · source: ' + d.source : ''}`}
        actions={<Badge variant={d.status === 'won' ? 'success' : d.status === 'lost' ? 'destructive' : 'accent'} className="capitalize">{d.status}</Badge>} />
      <Card className="mb-4"><CardContent className="pt-5">
        <ol className="flex flex-wrap items-center gap-1.5" aria-label="Stage progress">
          {open.map((s) => {
            const passed = cur && s.position < cur.position || d.status === 'won'
            const active = s.id === d.stage.id
            return (<li key={s.id}><button disabled={d.status === 'won'} onClick={() => go(s)} aria-current={active} className={cn('flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-default',
              active ? 'border-accent bg-accent text-accent-foreground' : passed ? 'border-success/40 bg-success/10 text-success' : 'bg-card text-muted-foreground hover:bg-secondary')}>{passed && <Check className="h-3 w-3" />}{s.name}</button></li>)
          })}
          {stages.filter((s) => s.is_won || s.is_lost).map((s) => (
            <li key={s.id}><button disabled={d.status === 'won' || s.id === d.stage.id} onClick={() => go(s)} className={cn('cursor-pointer rounded-full border px-3 py-1.5 text-xs font-semibold disabled:cursor-default',
              s.id === d.stage.id ? (s.is_won ? 'border-success bg-success text-white' : 'border-destructive bg-destructive text-white') : s.is_won ? 'border-success/50 text-success hover:bg-success/10' : 'border-destructive/40 text-destructive hover:bg-destructive/10')}>{s.is_won ? 'Closed' : 'Lost'}</button></li>))}
        </ol>
        {err && <div className="mt-3"><ErrorBox error={new Error(err)} /></div>}
        {d.status === 'lost' && <p className="mt-3 text-sm text-destructive">Lost: {d.lost_reason}</p>}
      </CardContent></Card>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Price" value={compactMoney(d.price)} />
        <Stat label="Probability" value={`${d.probability}%`} hint={`Stage: ${d.stage.name}`} />
        {d.gross_commission !== undefined ? <Stat label="Gross commission" value={compactMoney(d.gross_commission)} hint={d.weighted_commission != null ? `${compactMoney(d.weighted_commission)} weighted` : undefined} className="border-accent/50" /> : <Stat label="Commission" value="Restricted" />}
        <Stat label={d.status === 'won' ? 'Closed' : 'Expected close'} value={fmtDate(d.actual_close_date ?? d.expected_close_date)} />
        <Stat label="In stage" value={`${d.days_in_stage}d`} hint={d.rotting ? 'Past rotting threshold' : undefined} className={d.rotting ? 'border-destructive/50' : ''} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardTitle>Stage history</CardTitle></CardHeader><CardContent>
            <ol className="relative ml-2 border-l pl-5">
              {[...d.history].reverse().map((h) => (<li key={h.id} className="mb-4 last:mb-0"><span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-accent" />
                <div className="flex items-baseline justify-between"><span className="font-medium">{h.stage}</span><span className="text-xs text-muted-foreground">{fmtDate(h.at)}</span></div>
                <div className="text-xs text-muted-foreground">{h.from ? `from ${h.from}` : 'Created'} · {h.days} day{h.days === 1 ? '' : 's'} in stage{h.user ? ` · ${h.user}` : ''}{h.note ? ` · ${h.note}` : ''}</div></li>))}
            </ol>
          </CardContent></Card>
          <ActivityPanel recordType="deal" recordId={d.id} />
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Parties</CardTitle></CardHeader><CardContent><ul className="space-y-2 text-sm">
            {d.parties.map((p) => (<li key={p.id} className="flex justify-between gap-2"><span className="capitalize text-muted-foreground">{p.role.replace('_', ' ')}</span>
              {p.contact_id ? <EntityLink to={`/contacts/${p.contact_id}`}>{p.contact}</EntityLink> : <EntityLink to={`/companies/${p.company_id}`}>{p.company}</EntityLink>}</li>))}
            {d.parties.length === 0 && <li className="text-muted-foreground">No parties yet.</li>}
          </ul></CardContent></Card>
          <CustomFieldsCard entity="deal" path={`/deals/${d.id}`} values={(d as unknown as { custom: Record<string, unknown> }).custom} />
          <Card><CardHeader><CardTitle>Key dates</CardTitle></CardHeader><CardContent className="space-y-1.5 text-sm">
            {[['Listing expires', d.listing_expiration_date], ['Due diligence expires', d.dd_expiry_date], ['Loan contingency', d.loan_contingency_date], ['Closing', d.actual_close_date ?? d.expected_close_date]].map(([k, v]) => (
              <div key={k as string} className="flex justify-between"><span className="text-muted-foreground">{k}</span><span>{fmtDate(v as string)}</span></div>))}
            {d.property && <div className="border-t pt-2"><EntityLink to={`/properties/${d.property_id}`}>{d.property.address}, {d.property.city}</EntityLink></div>}
            {d.listing_id && <div><EntityLink to={`/listings/${d.listing_id}`}>Linked listing →</EntityLink></div>}
          </CardContent></Card>
          {d.splits && <Card><CardHeader><div className="flex items-center justify-between"><CardTitle>Commission splits</CardTitle><SplitsDialog deal={d} onDone={refresh} /></div></CardHeader><CardContent>
            {d.splits.length === 0 ? <p className="text-sm text-muted-foreground">No splits set.</p> : <ul className="space-y-1.5 text-sm">{d.splits.map((s) => (
              <li key={s.id} className="flex justify-between"><span>{s.external_name ?? `User #${s.recipient_user_id}`} <span className="text-xs capitalize text-muted-foreground">{s.kind.replace('_', ' ')}</span></span><span className="tabular-nums">{s.pct ? `${s.pct}% · ` : ''}{money(s.amount)}</span></li>))}</ul>}
          </CardContent></Card>}
        </div>
      </div>
      <StageMoveDialog deal={to ? d : null} to={to} onClose={() => setTo(null)} onDone={refresh} />
    </div>
  )
}

function SplitsDialog({ deal, onDone }: { deal: Detail; onDone: () => void }) {
  const users = useUsers()
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<{ who: string; pct: string }[]>(() => (deal.splits ?? []).filter((s) => s.pct).map((s) => ({ who: s.recipient_user_id ? `u${s.recipient_user_id}` : `x${s.external_name}`, pct: String(s.pct) })).concat([{ who: '', pct: '' }]))
  const [err, setErr] = useState('')
  const m = useSend<object>('PUT', `/deals/${deal.id}/splits`)
  const save = () => {
    const splits = rows.filter((r) => r.who && r.pct).map((r) => (r.who.startsWith('u') ? { recipient_user_id: Number(r.who.slice(1)), pct: Number(r.pct) } : { external_name: r.who.slice(1), pct: Number(r.pct) }))
    setErr(''); m.mutate({ splits }, { onSuccess: () => { onDone(); setOpen(false) }, onError: (e) => setErr((e as Error).message) })
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Pencil className="h-3.5 w-3.5" /> Edit</Button></DialogTrigger>
      <DialogContent><DialogTitle>Commission splits</DialogTitle><DialogDescription>Percentages of the gross commission. The backend rejects totals over 100%.</DialogDescription>
        <div className="mt-4 space-y-2">{rows.map((r, i) => (
          <div key={i} className="flex gap-2"><Select aria-label={`Recipient ${i + 1}`} className="flex-1" value={r.who} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, who: e.target.value } : x))}>
            <option value="">Recipient…</option>{users.data?.map((u) => <option key={u.id} value={`u${u.id}`}>{u.name}</option>)}
            {['CBRE (co-broker)', 'Marcus & Millichap (co-broker)', 'Lee & Associates (co-broker)', 'Referral fee'].map((x) => <option key={x} value={`x${x}`}>{x}</option>)}</Select>
            <Input aria-label={`Percent ${i + 1}`} className="w-24" type="number" placeholder="%" value={r.pct} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, pct: e.target.value } : x))} /></div>))}
          <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { who: '', pct: '' }])}>+ Add recipient</Button>
          {err && <ErrorBox error={new Error(err)} />}
          <Button className="w-full" onClick={save} disabled={m.isPending}>Save splits</Button></div>
      </DialogContent>
    </Dialog>
  )
}
