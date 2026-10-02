import { Link } from 'react-router-dom'
import { useApi, type Page } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { compactMoney, fmtDate } from '@/lib/utils'
import { StatusBadge, type ListingRow } from '@/pages/Listings'
import type { Lead } from '@/pages/Prospecting'
import { ScoreDial } from '@/pages/Prospecting'

export function PropertyPipeline({ propertyId }: { propertyId: number }) {
  const listings = useApi<Page<ListingRow>>('/listings', { property_id: propertyId, limit: 20 })
  const leads = useApi<Page<Lead>>('/leads', { property_id: propertyId, limit: 5 })
  return (
    <Card><CardHeader><CardTitle>Listings & prospecting</CardTitle></CardHeader><CardContent className="space-y-3">
      {leads.data?.items.map((l) => (
        <div key={l.id} className="flex items-center gap-3 rounded-lg border bg-background/60 p-3 text-sm"><ScoreDial score={l.score} />
          <div className="flex-1"><div className="font-medium">Prospecting lead · {l.name}</div><div className="text-xs text-muted-foreground">{l.trigger_reason?.matches.map((m) => m.rule).join(' · ') ?? l.source}</div></div><Badge variant="outline" className="capitalize">{l.status}</Badge></div>))}
      {listings.data?.items.map((l) => (
        <Link key={l.id} to={`/listings/${l.id}`} className="flex items-center justify-between rounded-lg border bg-background/60 p-3 text-sm hover:bg-secondary">
          <div><div className="font-medium">Sale listing · {compactMoney(l.status === 'closed' ? l.sold_price : l.list_price)}</div><div className="text-xs text-muted-foreground">{l.agreement_date ? `Signed ${fmtDate(l.agreement_date)}` : 'Not yet signed'} · {l.interest_total} buyers</div></div><StatusBadge s={l.status} /></Link>))}
      {leads.data && listings.data && leads.data.total + listings.data.total === 0 && <p className="text-sm text-muted-foreground">No listings or leads yet. Hold/sell triggers will flag this property when it qualifies.</p>}
    </CardContent></Card>
  )
}
