import { useParams } from 'react-router-dom'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { EntityLink, ErrorBox, Loading, Stat } from '@/components/common'
import { compactMoney, fmtDate } from '@/lib/utils'
import { AccBadge, type Investor } from '@/pages/Investors'
import { ActivityPanel } from '@/components/ActivityPanel'

interface Match { listing_id: number; address: string; city: string; property_type: string; list_price: number | null; score: number; reasons: string[] }

export default function InvestorDetail() {
  const { id } = useParams()
  const { data: i, isLoading, error } = useApi<Investor>(`/investors/${id}`)
  const matches = useApi<{ items: Match[] }>(`/investors/${id}/matches`)
  if (isLoading) return <Loading />
  if (error || !i) return <ErrorBox error={error} />
  return (
    <div className="rise">
      <PageHeader title={i.name} subtitle={[i.title, i.firm].filter(Boolean).join(' · ')} actions={<>{i.do_not_contact && <Badge variant="destructive">Do not contact</Badge>}<AccBadge s={i.accreditation_status} />{i.contact_id && <EntityLink to={`/contacts/${i.contact_id}`}>Contact record →</EntityLink>}</>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Check size" value={`${compactMoney(i.min_check)} – ${compactMoney(i.max_check)}`} />
        <Stat label="1031 exchange" value={i.exchange_1031 ? (i.days_to_1031 != null ? `${i.days_to_1031} days` : 'Yes') : 'No'} hint={i.exchange_1031 ? 'to deadline' : undefined} className={i.days_to_1031 != null && i.days_to_1031 < 60 ? 'border-destructive/50' : ''} />
        <Stat label="Committed / funded" value={compactMoney((i.commitment_totals.committed ?? 0) + (i.commitment_totals.funded ?? 0))} hint={`${i.commitments} fund position${i.commitments === 1 ? '' : 's'}`} />
        <Stat label="Preferred channel" value={<span className="capitalize">{i.preferred_channel.replace('_', ' ')}</span>} hint={i.owner_name ? `Relationship: ${i.owner_name}` : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardTitle>Matching active listings</CardTitle><p className="text-sm text-muted-foreground">Ranked suggestions only. Nothing is sent automatically.</p></CardHeader><CardContent>
            {matches.isLoading ? <Loading /> : matches.data?.items.length === 0 ? <p className="text-sm text-muted-foreground">No active listings fit this investor's criteria right now.</p> : (
              <ul className="divide-y">{matches.data!.items.slice(0, 8).map((m) => (
                <li key={m.listing_id} className="py-3"><div className="flex items-center justify-between"><EntityLink to={`/listings/${m.listing_id}`}>{m.address}, {m.city}</EntityLink><div className="flex items-center gap-2"><span className="text-sm tabular-nums">{compactMoney(m.list_price)}</span><Badge variant="accent">Score {m.score}</Badge></div></div>
                  <ul className="mt-1 list-inside list-disc text-xs text-muted-foreground">{m.reasons.map((r) => <li key={r}>{r}</li>)}</ul></li>))}</ul>)}
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Fund positions</CardTitle></CardHeader><CardContent>
            {i.commitment_list?.length ? <ul className="divide-y text-sm">{i.commitment_list.map((c) => (<li key={c.id} className="flex items-center justify-between py-2"><EntityLink to={`/funds/${c.fund_id}`}>{c.fund}</EntityLink><div className="flex items-center gap-2"><span className="tabular-nums">{compactMoney(c.amount)}</span><Badge variant={c.status === 'funded' ? 'success' : c.status === 'committed' ? 'accent' : 'secondary'} className="capitalize">{c.status.replace('_', ' ')}</Badge></div></li>))}</ul> : <p className="text-sm text-muted-foreground">No fund positions yet.</p>}
          </CardContent></Card>
          {i.contact_id && <ActivityPanel recordType="contact" recordId={i.contact_id} />}
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Criteria</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <div className="flex flex-wrap gap-1">{i.asset_classes.map((a) => <Badge key={a} variant="default" className="capitalize">{a}</Badge>)}</div>
            <div><span className="text-muted-foreground">Markets:</span> {i.markets.join(', ') || 'Any'}</div>
            {i.min_cap_rate_bps && <div><span className="text-muted-foreground">Min cap rate:</span> {(i.min_cap_rate_bps / 100).toFixed(2)}%</div>}
            {i.target_return_notes && <div><span className="text-muted-foreground">Targets:</span> {i.target_return_notes}</div>}
            {i.accreditation_verified_on && <div><span className="text-muted-foreground">Accreditation verified:</span> {fmtDate(i.accreditation_verified_on)}</div>}
            {i.notes && <div className="border-t pt-2 text-muted-foreground">{i.notes}</div>}
          </CardContent></Card>
          <p className="text-xs text-muted-foreground">Viewing investor profiles is recorded in the audit trail.</p>
        </div>
      </div>
    </div>
  )
}
