import { useNavigate } from 'react-router-dom'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Loading } from '@/components/common'
import { compactMoney, fmtDate } from '@/lib/utils'

export interface FundT {
  id: number; name: string; sponsor: string | null; status: string; target_raise: number; minimum_investment: number; strategy: string | null; target_return_notes: string | null
  opened_on: string | null; closing_date: string | null; by_status: Record<string, { amount: number; count: number }>; committed_or_funded: number; pct_of_target: number; investors: number; pipeline_interest: number
  properties?: { id: number; address: string; city: string }[]; deals?: { id: number; name: string; status: string }[]
}

export function FundBar({ f }: { f: FundT }) {
  const t = f.target_raise
  const seg = (v: number) => `${Math.min((v / t) * 100, 100)}%`
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${f.pct_of_target}% committed or funded`}>
        <div className="bg-success" style={{ width: seg(f.by_status.funded.amount) }} /><div className="bg-accent" style={{ width: seg(f.by_status.committed.amount) }} />
        <div className="bg-accent/50" style={{ width: seg(f.by_status.soft_circled.amount) }} /><div className="bg-accent/20" style={{ width: seg(f.by_status.interested.amount) }} />
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-success" />Funded {compactMoney(f.by_status.funded.amount)}</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />Committed {compactMoney(f.by_status.committed.amount)}</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-accent/50" />Soft-circled {compactMoney(f.by_status.soft_circled.amount)}</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-accent/20" />Interested {compactMoney(f.by_status.interested.amount)}</span>
      </div>
    </div>
  )
}

export const FundStatus = ({ s }: { s: string }) => <Badge variant={s === 'raising' ? 'accent' : s === 'closed' || s === 'deployed' ? 'success' : 'secondary'} className="capitalize">{s}</Badge>

export default function Funds() {
  const nav = useNavigate()
  const { data, isLoading } = useApi<{ items: FundT[] }>('/funds')
  const tot = data?.items.reduce((a, f) => a + f.committed_or_funded, 0)
  return (
    <div className="rise">
      <PageHeader title="Funds & Syndications" subtitle={data ? `${compactMoney(tot)} committed or funded across ${data.items.length} vehicles` : undefined} />
      {isLoading ? <Loading /> : <div className="grid gap-4 lg:grid-cols-2">{data!.items.map((f) => (
        <Card key={f.id} className="cursor-pointer transition-shadow hover:shadow-md" onClick={() => nav(`/funds/${f.id}`)} data-testid="fund-card"><CardContent className="pt-5">
          <div className="flex items-start justify-between"><div><h3 className="font-display text-xl font-semibold">{f.name}</h3><p className="text-sm text-muted-foreground">{f.strategy}</p></div><FundStatus s={f.status} /></div>
          <div className="my-4 flex items-end justify-between"><div><div className="font-display text-4xl font-semibold">{f.pct_of_target}%</div><div className="text-xs text-muted-foreground">of {compactMoney(f.target_raise)} target committed or funded</div></div>
            <div className="text-right text-sm"><div>{f.investors} investors</div><div className="text-xs text-muted-foreground">min {compactMoney(f.minimum_investment)}{f.closing_date ? ` · ${f.status === 'raising' ? 'closes' : 'closed'} ${fmtDate(f.closing_date)}` : ''}</div></div></div>
          <FundBar f={f} />
        </CardContent></Card>))}</div>}
    </div>
  )
}
