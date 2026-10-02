import { useParams } from 'react-router-dom'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { EntityLink, ErrorBox, Loading, Stat } from '@/components/common'
import { compactMoney, fmtDate } from '@/lib/utils'
import { ActivityPanel } from '@/components/ActivityPanel'

interface D {
  id: number; name: string; kind: string; website: string | null; address: string | null; city: string | null; state: string | null; owner_name: string | null
  properties_count: number; portfolio_value: number; parent: { id: number; name: string } | null; children: { id: number; name: string }[]
  principals: { role_id: number; contact_id: number; name: string; role: string; is_primary: boolean; title: string | null; end_date: string | null }[]
  holdings: { ownership_id: number; property_id: number; address: string; city: string; property_type: string; acquired_date: string | null; disposed_date: string | null; ownership_pct: number; estimated_value: number | null }[]
}

export default function CompanyDetail() {
  const { id } = useParams()
  const { data: c, isLoading, error } = useApi<D>(`/companies/${id}`)
  if (isLoading) return <Loading />
  if (error || !c) return <ErrorBox error={error} />
  const current = c.holdings.filter((h) => !h.disposed_date)
  const past = c.holdings.filter((h) => h.disposed_date)
  return (
    <div className="rise">
      <PageHeader title={c.name} subtitle={`${c.kind.replace('_', ' ')} · ${[c.address, c.city].filter(Boolean).join(', ')}`} actions={c.parent ? <Badge variant="outline">Subsidiary of {c.parent.name}</Badge> : undefined} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Properties held" value={c.properties_count} />
        <Stat label="Portfolio value" value={compactMoney(c.portfolio_value)} hint="current holdings" />
        <Stat label="Principals" value={c.principals.filter((p) => !p.end_date).length} />
        <Stat label="Broker" value={c.owner_name ?? '—'} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardTitle>Current holdings</CardTitle></CardHeader><CardContent className="px-0">
            {current.length === 0 ? <p className="px-5 text-sm text-muted-foreground">No current properties.</p> : (
              <Table><THead><TR><TH>Property</TH><TH>Type</TH><TH>Acquired</TH><TH className="text-right">Share</TH><TH className="text-right">Value</TH></TR></THead>
                <TBody>{current.map((h) => (
                  <TR key={h.ownership_id}><TD><EntityLink to={`/properties/${h.property_id}`}>{h.address}</EntityLink><div className="text-xs text-muted-foreground">{h.city}</div></TD>
                    <TD className="capitalize">{h.property_type}</TD><TD>{fmtDate(h.acquired_date)}</TD><TD className="text-right">{h.ownership_pct}%</TD><TD className="text-right">{compactMoney(h.estimated_value)}</TD></TR>))}
                </TBody></Table>)}
          </CardContent></Card>
          {past.length > 0 && <Card><CardHeader><CardTitle>Sold / disposed</CardTitle></CardHeader><CardContent><ul className="divide-y text-sm">{past.map((h) => (
            <li key={h.ownership_id} className="flex justify-between py-2"><EntityLink to={`/properties/${h.property_id}`}>{h.address}, {h.city}</EntityLink><span className="text-muted-foreground">{fmtDate(h.acquired_date)} → {fmtDate(h.disposed_date)}</span></li>))}</ul></CardContent></Card>}
          <ActivityPanel recordType="company" recordId={c.id} />
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>People behind the entity</CardTitle></CardHeader><CardContent><ul className="space-y-3">
            {c.principals.map((p) => (<li key={p.role_id} className="text-sm"><EntityLink to={`/contacts/${p.contact_id}`}>{p.name}</EntityLink>
              <div className="text-xs capitalize text-muted-foreground">{p.role.replace('_', ' ')}{p.is_primary ? ' · decision-maker' : ''}{p.title ? ` · ${p.title}` : ''}</div></li>))}
          </ul></CardContent></Card>
          {c.children.length > 0 && <Card><CardHeader><CardTitle>Related entities</CardTitle></CardHeader><CardContent><ul className="space-y-1 text-sm">{c.children.map((k) => <li key={k.id}><EntityLink to={`/companies/${k.id}`}>{k.name}</EntityLink></li>)}</ul></CardContent></Card>}
        </div>
      </div>
    </div>
  )
}
