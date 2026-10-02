import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EntityLink, ErrorBox, Field, Loading, Stat } from '@/components/common'
import { compactMoney, fmtDate, money } from '@/lib/utils'
import { FundBar, FundStatus, type FundT } from '@/pages/Funds'
import type { Investor } from '@/pages/Investors'

interface Row { id: number; investor_id: number; investor: string; amount: number; status: string; interested_on: string | null; committed_on: string | null; funded_on: string | null; accreditation_status?: string }
const ORDER = ['interested', 'soft_circled', 'committed', 'funded']

export default function FundDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: f, isLoading, error } = useApi<FundT>(`/funds/${id}`)
  const rows = useApi<{ items: Row[] }>(`/funds/${id}/commitments`)
  const [err, setErr] = useState('')
  const move = useSend<{ id: number; status: string }>('POST', (b) => `/commitments/${b.id}/status`)
  if (isLoading) return <Loading />
  if (error || !f) return <ErrorBox error={error} />
  const refresh = () => qc.invalidateQueries()
  return (
    <div className="rise">
      <PageHeader title={f.name} subtitle={`${f.strategy ?? ''}${f.target_return_notes ? ' · ' + f.target_return_notes : ''}`} actions={<FundStatus s={f.status} />} />
      <Card className="mb-4"><CardContent className="pt-5"><div className="mb-3 flex items-end justify-between"><div><div className="font-display text-5xl font-semibold">{f.pct_of_target}%</div><div className="text-sm text-muted-foreground">{compactMoney(f.committed_or_funded)} committed or funded of {compactMoney(f.target_raise)}</div></div>
        <div className="text-right text-sm text-muted-foreground">Opened {fmtDate(f.opened_on)}{f.closing_date ? ` · target close ${fmtDate(f.closing_date)}` : ''}</div></div><FundBar f={f} /></CardContent></Card>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Investors" value={f.investors} /><Stat label="Minimum" value={compactMoney(f.minimum_investment)} /><Stat label="Total interest" value={compactMoney(f.pipeline_interest)} hint="all stages" /><Stat label="Remaining" value={compactMoney(Math.max(f.target_raise - f.committed_or_funded, 0))} />
      </div>
      {err && <div className="mb-3"><ErrorBox error={new Error(err)} /></div>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader><div className="flex items-center justify-between"><CardTitle>Commitments</CardTitle>{f.status !== 'closed' && f.status !== 'deployed' && <AddCommitment fundId={f.id} onDone={refresh} />}</div></CardHeader><CardContent className="px-0">
          <Table><THead><TR><TH>Investor</TH><TH className="text-right">Amount</TH><TH>Status</TH>{rows.data?.items[0] && 'accreditation_status' in rows.data.items[0] && <TH>Accred.</TH>}<TH>Since</TH><TH>Advance</TH></TR></THead>
            <TBody>{rows.data?.items.map((r) => (<TR key={r.id}><TD><EntityLink to={`/investors/${r.investor_id}`}>{r.investor}</EntityLink></TD><TD className="text-right tabular-nums">{money(r.amount)}</TD>
              <TD><Badge variant={r.status === 'funded' ? 'success' : r.status === 'committed' ? 'accent' : 'secondary'} className="capitalize">{r.status.replace('_', ' ')}</Badge></TD>
              {'accreditation_status' in r && <TD className="text-xs capitalize text-muted-foreground">{r.accreditation_status?.replace('_', ' ')}</TD>}
              <TD className="text-muted-foreground">{fmtDate(r.funded_on ?? r.committed_on ?? r.interested_on)}</TD>
              <TD>{r.status !== 'funded' && f.status !== 'closed' && f.status !== 'deployed' && (
                <Select aria-label={`Advance ${r.investor}`} value="" className="h-8 text-xs" onChange={(e) => { setErr(''); e.target.value && move.mutate({ id: r.id, status: e.target.value }, { onSuccess: refresh, onError: (x) => setErr((x as Error).message) }) }}>
                  <option value="">Move to…</option>{ORDER.filter((s) => ORDER.indexOf(s) > ORDER.indexOf(r.status)).map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}</Select>)}</TD></TR>))}</TBody></Table>
        </CardContent></Card>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Properties</CardTitle></CardHeader><CardContent><ul className="space-y-1.5 text-sm">{f.properties?.map((p) => <li key={p.id}><EntityLink to={`/properties/${p.id}`}>{p.address}, {p.city}</EntityLink></li>)}{!f.properties?.length && <li className="text-muted-foreground">None linked.</li>}</ul></CardContent></Card>
          <Card><CardHeader><CardTitle>Capital deals</CardTitle></CardHeader><CardContent><ul className="space-y-1.5 text-sm">{f.deals?.map((d) => <li key={d.id}><EntityLink to={`/deals/${d.id}`}>{d.name}</EntityLink> <Badge variant="outline" className="capitalize">{d.status}</Badge></li>)}{!f.deals?.length && <li className="text-muted-foreground">None linked.</li>}</ul></CardContent></Card>
        </div>
      </div>
    </div>
  )
}

function AddCommitment({ fundId, onDone }: { fundId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [inv, setInv] = useState<Investor | null>(null)
  const [amount, setAmount] = useState('')
  const [err, setErr] = useState('')
  const found = useApi<Page<Investor>>('/investors', { q, limit: 6 }, { enabled: q.length >= 2 && !inv })
  const m = useSend<object>('POST', '/commitments')
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="accent"><Plus className="h-4 w-4" /> Add commitment</Button></DialogTrigger>
      <DialogContent><DialogTitle>Add commitment</DialogTitle><DialogDescription>Starts as interested. Committing requires an accredited investor and respects the fund target.</DialogDescription>
        <div className="mt-4 space-y-3">{!inv ? (<><Field label="Find investor"><Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} /></Field>
          <ul className="divide-y rounded-md border">{found.data?.items.map((i) => <li key={i.id}><button className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-secondary" onClick={() => setInv(i)}>{i.name}</button></li>)}</ul></>) : (<>
          <div className="rounded-md border bg-background p-3 text-sm font-medium">{inv.name}</div>
          <Field label="Amount"><Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button className="w-full" onClick={() => m.mutate({ investor_id: inv.id, fund_id: fundId, amount: Number(amount) }, { onSuccess: () => { onDone(); setOpen(false); setInv(null); setAmount('') }, onError: (e) => setErr((e as Error).message) })}>Add</Button></>)}</div>
      </DialogContent>
    </Dialog>
  )
}
