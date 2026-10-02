import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading, Pagination, Stat } from '@/components/common'
import { compactMoney, cn, fmtDate, money } from '@/lib/utils'
import type { PropRow } from '@/pages/Properties'

export interface ListingRow {
  id: number; property_id: number; address: string; city: string; property_name: string | null; property_type: string; subtype: string | null; building_sf: number | null
  status: string; list_price: number | null; sold_price: number | null; price_per_sf: number | null; cap_rate_bps: number | null; agreement_date: string | null
  expiration_date: string | null; active_date: string | null; days_on_market: number | null; days_to_expiration: number | null; seller_company: string | null; seller_contact: string | null
  confidential: boolean; owner_name: string | null; brokers: { user_id: number; name: string; role: string; split_pct: number }[]; interest_total: number; funnel: Record<string, number>
  commission_rate_bps?: number | null; commission_terms?: string | null; expected_commission?: number | null; deal_id: number | null; market: string | null
}

export const STATUS_VARIANT: Record<string, 'secondary' | 'success' | 'warning' | 'destructive' | 'accent' | 'default'> = {
  prospect: 'secondary', active: 'success', under_contract: 'accent', closed: 'default', expired: 'destructive', withdrawn: 'warning',
}
export const StatusBadge = ({ s }: { s: string }) => <Badge variant={STATUS_VARIANT[s] ?? 'secondary'} className="capitalize">{s.replace('_', ' ')}</Badge>

const STATUSES = ['', 'prospect', 'active', 'under_contract', 'closed', 'expired', 'withdrawn']

export default function Listings() {
  const nav = useNavigate()
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [expiring, setExpiring] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const summary = useApi<{ by_status: Record<string, { count: number; value: number }>; expiring_60_days: number }>('/listings/summary')
  const { data, isLoading, error } = useApi<Page<ListingRow>>('/listings', { status, type, q, expiring_within_days: expiring, page, limit: 20, sort: expiring ? 'expiration' : 'recent' })
  const s = summary.data
  return (
    <div className="rise">
      <PageHeader title="Listings" subtitle="Sale listings from prospect to close, with buyer interest on every one" actions={<NewListing />} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Active" value={s?.by_status.active.count ?? '—'} hint={s ? `${compactMoney(s.by_status.active.value)} on market` : undefined} />
        <Stat label="Under contract" value={s?.by_status.under_contract.count ?? '—'} hint={s ? compactMoney(s.by_status.under_contract.value) : undefined} />
        <Stat label="Closed (12 mo)" value={s?.by_status.closed.count ?? '—'} hint={s ? compactMoney(s.by_status.closed.value) : undefined} />
        <Stat label="Prospects" value={s?.by_status.prospect.count ?? '—'} hint="not yet signed" />
        <Stat label="Expiring ≤ 60 days" value={s?.expiring_60_days ?? '—'} hint="renewal calls due" className={s && s.expiring_60_days > 0 ? 'border-warning/50' : ''} />
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b p-4">
          <div className="flex flex-wrap gap-1" role="tablist">
            {STATUSES.map((st) => (<button key={st} role="tab" aria-selected={status === st} onClick={() => { setStatus(st); setPage(1) }}
              className={cn('cursor-pointer rounded-full px-3 py-1 text-xs font-semibold capitalize', status === st ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-secondary')}>{st ? st.replace('_', ' ') : 'All'}</button>))}
          </div>
          <Input aria-label="Filter listings" className="ml-auto max-w-[14rem]" placeholder="Address or city…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
          <Select aria-label="Property type" value={type} onChange={(e) => { setType(e.target.value); setPage(1) }}><option value="">All types</option><option value="retail">Retail</option><option value="industrial">Industrial</option></Select>
          <Select aria-label="Expiration" value={expiring} onChange={(e) => { setExpiring(e.target.value); setPage(1) }}><option value="">Any expiration</option><option value="30">Expiring ≤ 30 days</option><option value="60">Expiring ≤ 60 days</option><option value="90">Expiring ≤ 90 days</option></Select>
        </div>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (<>
          <Table>
            <THead><TR><TH>Property</TH><TH>Status</TH><TH>Seller</TH><TH className="text-right">List price</TH><TH className="text-right">$/SF</TH><TH className="text-right">Cap</TH><TH className="text-right">DOM</TH><TH>Expires</TH><TH className="text-right">Buyers</TH><TH>Broker</TH></TR></THead>
            <TBody>{data!.items.map((l) => (
              <TR key={l.id} className="cursor-pointer" onClick={() => nav(`/listings/${l.id}`)}>
                <TD><div className="font-medium">{l.property_name ?? l.address}</div><div className="text-xs text-muted-foreground">{l.address !== l.property_name && l.property_name ? `${l.address}, ` : ''}{l.city} · <span className="capitalize">{l.property_type}</span></div></TD>
                <TD><StatusBadge s={l.status} />{l.confidential && <Badge variant="outline" className="ml-1">Conf.</Badge>}</TD>
                <TD className="text-sm">{l.seller_company ?? l.seller_contact ?? '—'}</TD>
                <TD className="text-right tabular-nums">{l.status === 'closed' ? money(l.sold_price) : compactMoney(l.list_price)}</TD>
                <TD className="text-right tabular-nums">{l.price_per_sf ? `$${l.price_per_sf}` : '—'}</TD>
                <TD className="text-right tabular-nums">{l.cap_rate_bps ? `${(l.cap_rate_bps / 100).toFixed(2)}%` : '—'}</TD>
                <TD className="text-right tabular-nums">{l.days_on_market ?? '—'}</TD>
                <TD>{l.expiration_date ? <span className={cn(l.days_to_expiration != null && l.days_to_expiration >= 0 && l.days_to_expiration <= 60 && l.status === 'active' && 'font-semibold text-destructive')}>{fmtDate(l.expiration_date)}</span> : '—'}</TD>
                <TD className="text-right tabular-nums">{l.interest_total}</TD>
                <TD>{l.owner_name}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination page={page} limit={20} total={data!.total} onPage={setPage} />
        </>)}
      </Card>
    </div>
  )
}

function NewListing() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [prop, setProp] = useState<PropRow | null>(null)
  const [price, setPrice] = useState('')
  const [err, setErr] = useState('')
  const found = useApi<Page<PropRow>>('/properties', { q, limit: 5 }, { enabled: q.length >= 2 && !prop })
  const m = useSend<unknown, { id: number }>('POST', '/listings', ['/listings'])
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="accent"><Plus className="h-4 w-4" /> New listing</Button></DialogTrigger>
      <DialogContent>
        <DialogTitle>New listing</DialogTitle>
        <DialogDescription>Starts as a prospect. Activation requires price, agreement and expiration dates.</DialogDescription>
        <div className="mt-4 space-y-3">
          {!prop ? (<>
            <Field label="Find property"><Input autoFocus placeholder="Address, city or APN…" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
            <ul className="divide-y rounded-md border">{found.data?.items.map((p) => (<li key={p.id}><button className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-secondary" onClick={() => setProp(p)}>{p.address}, {p.city} <span className="text-xs text-muted-foreground">· {p.current_owner}</span></button></li>))}</ul>
          </>) : (<>
            <div className="rounded-md border bg-background p-3 text-sm"><div className="font-medium">{prop.address}, {prop.city}</div><div className="text-xs text-muted-foreground">Owner: {prop.current_owner}</div><button className="mt-1 cursor-pointer text-xs text-primary underline" onClick={() => setProp(null)}>Change</button></div>
            <Field label="Target list price"><Input type="number" value={price} onChange={(e) => setPrice(e.target.value)} placeholder={prop.estimated_value ? String(prop.estimated_value) : ''} /></Field>
            {err && <ErrorBox error={new Error(err)} />}
            <Button className="w-full" disabled={m.isPending} onClick={() => m.mutate({ property_id: prop.id, list_price: price ? Number(price) : null }, { onSuccess: (r) => { setOpen(false); nav(`/listings/${r.id}`) }, onError: (e) => setErr((e as Error).message) })}>Create listing</Button>
          </>)}
        </div>
      </DialogContent>
    </Dialog>
  )
}
