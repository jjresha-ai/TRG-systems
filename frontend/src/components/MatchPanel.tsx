import { useState } from 'react'
import { useApi } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Select } from '@/components/ui/select'
import { EntityLink, Loading } from '@/components/common'

interface M { investor_id: number; name: string; score: number; reasons: string[]; blocked_do_not_contact: boolean; min_check: number | null; max_check: number | null; accreditation_status?: string }

export function MatchPanel({ listingId }: { listingId: number }) {
  const [ltv, setLtv] = useState('60')
  const { data, isLoading } = useApi<{ items: M[] }>(`/listings/${listingId}/matches`, { ltv_pct: ltv })
  return (
    <Card><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>Matching investors</CardTitle>
      <Select aria-label="Assumed LTV" value={ltv} onChange={(e) => setLtv(e.target.value)} className="h-8 text-xs">{[['0', 'All cash'], ['40', '40% LTV'], ['60', '60% LTV'], ['70', '70% LTV']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></div>
      <p className="text-sm text-muted-foreground">Ranked by asset class, market, equity vs check size, 1031 timing. A suggestion, never an automatic send.</p></CardHeader>
      <CardContent>{isLoading ? <Loading /> : data?.items.length === 0 ? <p className="text-sm text-muted-foreground">No investors fit at this leverage.</p> : (
        <ul className="divide-y" data-testid="matches">{data!.items.slice(0, 8).map((m) => (
          <li key={m.investor_id} className="py-2.5"><div className="flex items-center justify-between"><EntityLink to={`/investors/${m.investor_id}`}>{m.name}</EntityLink>
            <div className="flex items-center gap-1.5">{m.blocked_do_not_contact && <Badge variant="destructive">DNC</Badge>}<Badge variant="accent">Score {m.score}</Badge></div></div>
            <ul className="mt-0.5 list-inside list-disc text-xs text-muted-foreground">{m.reasons.map((r) => <li key={r}>{r}</li>)}</ul></li>))}</ul>)}</CardContent></Card>
  )
}
