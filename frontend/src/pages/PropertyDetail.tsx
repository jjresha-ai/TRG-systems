import { useParams } from 'react-router-dom'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { EntityLink, ErrorBox, HoldBadge, Loading, MaturityBadge, Stat, ago } from '@/components/common'
import { compactMoney, fmtDate, money, num } from '@/lib/utils'
import { ActivityPanel } from '@/components/ActivityPanel'
import { CustomFieldsCard } from '@/components/CustomFieldsCard'
import { PropertyPipeline } from '@/components/PropertyPipeline'

interface D {
  id: number; name: string | null; address: string; city: string; zip: string | null; apn: string | null; county: string; property_type: string; subtype: string | null
  market: string | null; submarket: string | null; building_sf: number | null; land_acres: number | null; year_built: number | null; zoning: string | null
  noi: number | null; cap_rate_bps: number | null; estimated_value: number | null; lender: string | null; loan_original_amount: number | null; loan_rate_type: string | null
  loan_maturity_date: string | null; hold_intent: string; pricing_expectation: number | null; hold_years: number | null; owner_name: string | null; last_contact_at: string | null; tags: string[]
  custom: Record<string, unknown>
  owners: { company_id: number | null; company: string | null; contact_id: number | null; name?: string; pct: number; principals: { id: number; name: string; role: string }[] }[]
  ownership_history: { id: number; company_id: number | null; company: string | null; contact_id: number | null; contact: string | null; ownership_pct: number; acquired_date: string | null; disposed_date: string | null; acquisition_price: number | null }[]
}

export default function PropertyDetail() {
  const { id } = useParams()
  const { data: p, isLoading, error } = useApi<D>(`/properties/${id}`)
  if (isLoading) return <Loading />
  if (error || !p) return <ErrorBox error={error} />
  return (
    <div className="rise">
      <PageHeader title={p.name ?? p.address} subtitle={`${p.name ? p.address + ', ' : ''}${p.city}, CA ${p.zip ?? ''} · APN ${p.apn ?? '—'} · ${p.county} County`}
        actions={<><Badge variant={p.property_type === 'retail' ? 'accent' : 'default'} className="capitalize">{p.property_type}</Badge>{p.subtype && <Badge variant="outline">{p.subtype}</Badge>}<HoldBadge h={p.hold_intent} /></>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Est. value" value={compactMoney(p.estimated_value)} hint={p.pricing_expectation ? `Owner expects ${compactMoney(p.pricing_expectation)}` : undefined} />
        <Stat label="NOI / Cap" value={compactMoney(p.noi)} hint={p.cap_rate_bps ? `${(p.cap_rate_bps / 100).toFixed(2)}% cap` : undefined} />
        <Stat label="Building" value={`${num(p.building_sf)} SF`} hint={`${p.land_acres ?? '—'} acres · built ${p.year_built ?? '—'}`} />
        <Stat label="Hold period" value={p.hold_years != null ? `${p.hold_years} yrs` : '—'} hint="since current acquisition" />
        <Stat label="Last contact" value={ago(p.last_contact_at)} hint={p.owner_name ? `Broker: ${p.owner_name}` : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardTitle>Who owns this</CardTitle></CardHeader><CardContent>
            {p.owners.map((o, i) => (
              <div key={i} className="mb-3 rounded-lg border bg-background/60 p-4 last:mb-0">
                <div className="flex items-center justify-between">
                  <div className="font-display text-lg font-semibold">{o.company_id ? <EntityLink to={`/companies/${o.company_id}`}>{o.company}</EntityLink> : <EntityLink to={`/contacts/${o.contact_id}`}>{o.name}</EntityLink>}</div>
                  <Badge variant="outline">{o.pct}%</Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
                  {o.principals.map((pr) => <span key={pr.id}><EntityLink to={`/contacts/${pr.id}`}>{pr.name}</EntityLink> <span className="text-xs capitalize text-muted-foreground">{pr.role.replace('_', ' ')}</span></span>)}
                </div>
              </div>))}
          </CardContent></Card>
          <PropertyPipeline propertyId={p.id} />
          <Card><CardHeader><CardTitle>Ownership history</CardTitle></CardHeader><CardContent className="px-0">
            <Table><THead><TR><TH>Owner</TH><TH>Acquired</TH><TH>Disposed</TH><TH className="text-right">Share</TH><TH className="text-right">Price</TH></TR></THead>
              <TBody>{p.ownership_history.map((h) => (<TR key={h.id}><TD>{h.company_id ? <EntityLink to={`/companies/${h.company_id}`}>{h.company}</EntityLink> : h.contact}</TD>
                <TD>{fmtDate(h.acquired_date)}</TD><TD>{h.disposed_date ? fmtDate(h.disposed_date) : <Badge variant="success">Current</Badge>}</TD><TD className="text-right">{h.ownership_pct}%</TD><TD className="text-right">{h.acquisition_price ? money(h.acquisition_price) : '—'}</TD></TR>))}
              </TBody></Table>
          </CardContent></Card>
          <ActivityPanel recordType="property" recordId={p.id} />
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Debt</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <Row k="Lender" v={p.lender ?? 'Unencumbered / unknown'} />
            <Row k="Original loan" v={p.loan_original_amount ? money(p.loan_original_amount) : '—'} />
            <Row k="Rate type" v={<span className="capitalize">{p.loan_rate_type ?? '—'}</span>} />
            <Row k="Maturity" v={<span className="flex items-center gap-2">{fmtDate(p.loan_maturity_date)} <MaturityBadge d={p.loan_maturity_date} /></span>} />
          </CardContent></Card>
          <CustomFieldsCard entity="property" path={`/properties/${p.id}`} values={p.custom} />
          <Card><CardHeader><CardTitle>Physical</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <Row k="Market" v={`${p.market} · ${p.submarket}`} /><Row k="Zoning" v={p.zoning ?? '—'} /><Row k="Year built" v={p.year_built ?? '—'} />
          </CardContent></Card>
          {p.tags.length > 0 && <div className="flex flex-wrap gap-1.5">{p.tags.map((t) => <Badge key={t} variant="accent">{t}</Badge>)}</div>}
        </div>
      </div>
    </div>
  )
}

const Row = ({ k, v }: { k: string; v: React.ReactNode }) => <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v}</span></div>
