import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { ago, ErrorBox, HoldBadge, Loading, MaturityBadge, Pagination } from '@/components/common'
import { compactMoney, num } from '@/lib/utils'
import { NewProperty } from '@/components/NewProperty'

export interface PropRow {
  id: number; address: string; city: string; property_type: string; subtype: string | null; market: string | null; building_sf: number | null
  estimated_value: number | null; cap_rate_bps: number | null; loan_maturity_date: string | null; hold_intent: string; hold_years: number | null
  current_owner: string | null; principal: string | null; owner_name: string | null; last_contact_at: string | null; name: string | null
}

export default function Properties() {
  const nav = useNavigate()
  const [f, setF] = useState({ q: '', type: '', market: '', hold_intent: '', maturity_within_months: '', held_at_least_years: '', sort: 'address' })
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useApi<Page<PropRow>>('/properties', { ...f, page, limit: 25 })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  return (
    <div className="rise">
      <PageHeader title="Properties" subtitle={data ? `${data.total} retail and industrial assets with ownership and debt` : undefined} actions={<NewProperty />} />
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-4">
          <Input aria-label="Filter properties" className="max-w-xs" placeholder="Address, city, APN, name…" value={f.q} onChange={set('q')} />
          <Select aria-label="Property type" value={f.type} onChange={set('type')}><option value="">Retail + Industrial</option><option value="retail">Retail</option><option value="industrial">Industrial</option></Select>
          <Select aria-label="Market" value={f.market} onChange={set('market')}><option value="">All markets</option>{['Orange County', 'Los Angeles', 'Inland Empire', 'San Diego'].map((m) => <option key={m}>{m}</option>)}</Select>
          <Select aria-label="Hold intent" value={f.hold_intent} onChange={set('hold_intent')}><option value="">Any intent</option><option value="open_to_sell">Open to sell</option><option value="selling_soon">Selling soon</option><option value="hold">Holding</option><option value="unknown">Unknown</option></Select>
          <Select aria-label="Loan maturity" value={f.maturity_within_months} onChange={set('maturity_within_months')}><option value="">Any maturity</option><option value="12">Loan matures ≤ 12 mo</option><option value="24">Loan matures ≤ 24 mo</option></Select>
          <Select aria-label="Hold period" value={f.held_at_least_years} onChange={set('held_at_least_years')}><option value="">Any hold period</option><option value="7">Held 7+ years</option><option value="10">Held 10+ years</option><option value="15">Held 15+ years</option></Select>
          <Select aria-label="Sort" value={f.sort} onChange={set('sort')}><option value="address">Sort: address</option><option value="value">Sort: value</option><option value="maturity">Sort: loan maturity</option><option value="sf">Sort: size</option></Select>
        </div>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (<>
          <Table>
            <THead><TR><TH>Property</TH><TH>Type</TH><TH>Owner</TH><TH className="text-right">SF</TH><TH className="text-right">Value</TH><TH>Hold</TH><TH>Loan maturity</TH><TH>Intent</TH><TH>Last touch</TH></TR></THead>
            <TBody>{data!.items.map((p) => (
              <TR key={p.id} className="cursor-pointer" onClick={() => nav(`/properties/${p.id}`)}>
                <TD><div className="font-medium">{p.name ?? p.address}</div><div className="text-xs text-muted-foreground">{p.name ? `${p.address}, ` : ''}{p.city}</div></TD>
                <TD><Badge variant={p.property_type === 'retail' ? 'accent' : 'default'} className="capitalize">{p.property_type}</Badge><div className="mt-0.5 text-xs text-muted-foreground">{p.subtype}</div></TD>
                <TD><div>{p.current_owner}</div><div className="text-xs text-muted-foreground">{p.principal}</div></TD>
                <TD className="text-right tabular-nums">{num(p.building_sf)}</TD>
                <TD className="text-right tabular-nums">{compactMoney(p.estimated_value)}</TD>
                <TD className="tabular-nums">{p.hold_years != null ? `${p.hold_years} yrs` : '—'}</TD>
                <TD><MaturityBadge d={p.loan_maturity_date} /></TD>
                <TD><HoldBadge h={p.hold_intent} /></TD>
                <TD className="text-muted-foreground">{ago(p.last_contact_at)}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination page={page} limit={25} total={data!.total} onPage={setPage} />
        </>)}
      </Card>
    </div>
  )
}
