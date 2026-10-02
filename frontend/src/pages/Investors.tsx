import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Clock, ShieldCheck } from 'lucide-react'
import { useApi, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { ErrorBox, Loading, Pagination } from '@/components/common'
import { compactMoney } from '@/lib/utils'

export interface Investor {
  id: number; name: string; title: string | null; firm: string | null; contact_id: number | null; company_id: number | null; asset_classes: string[]; markets: string[]
  min_check: number | null; max_check: number | null; exchange_1031: boolean; days_to_1031: number | null; accreditation_status?: string; accreditation_verified_on?: string | null
  commitment_totals: Record<string, number>; commitments: number; preferred_channel: string; do_not_contact: boolean; target_return_notes: string | null; min_cap_rate_bps: number | null
  owner_name: string | null; notes?: string | null
  commitment_list?: { id: number; fund_id: number; fund: string; amount: number; status: string; committed_on: string | null }[]
}

export const AccBadge = ({ s }: { s?: string }) => {
  if (!s) return null
  const m: Record<string, 'success' | 'warning' | 'secondary' | 'destructive'> = { accredited: 'success', pending: 'warning', unknown: 'secondary', not_accredited: 'destructive' }
  return <Badge variant={m[s]} className="capitalize"><ShieldCheck className="h-3 w-3" />{s.replace('_', ' ')}</Badge>
}

export default function Investors() {
  const nav = useNavigate()
  const [f, setF] = useState({ q: '', asset_class: '', market: '', only_1031: '', accreditation: '' })
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useApi<Page<Investor>>('/investors', { ...f, only_1031: f.only_1031 || undefined, page, limit: 20 })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  const showAcc = data?.items[0] && 'accreditation_status' in data.items[0]
  return (
    <div className="rise">
      <PageHeader title="Investors" subtitle={data ? `${data.total} investor profiles for 1880 Capital and listing matching` : undefined} />
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-4">
          <Input aria-label="Filter investors" className="max-w-xs" placeholder="Investor or firm…" value={f.q} onChange={set('q')} />
          <Select aria-label="Asset class" value={f.asset_class} onChange={set('asset_class')}><option value="">Any asset class</option><option value="retail">Retail</option><option value="industrial">Industrial</option></Select>
          <Select aria-label="Market" value={f.market} onChange={set('market')}><option value="">Any market</option>{['Orange County', 'Los Angeles', 'Inland Empire', 'San Diego'].map((m) => <option key={m}>{m}</option>)}</Select>
          <Select aria-label="1031" value={f.only_1031} onChange={set('only_1031')}><option value="">1031: any</option><option value="true">1031 buyers only</option></Select>
          <Select aria-label="Accreditation" value={f.accreditation} onChange={set('accreditation')}><option value="">Any accreditation</option>{['accredited', 'pending', 'unknown', 'not_accredited'].map((a) => <option key={a} value={a}>{a.replace('_', ' ')}</option>)}</Select>
        </div>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (<>
          <Table>
            <THead><TR><TH>Investor</TH><TH>Focus</TH><TH className="text-right">Check size</TH><TH>1031</TH>{showAcc && <TH>Accreditation</TH>}<TH className="text-right">In funds</TH><TH>Channel</TH></TR></THead>
            <TBody>{data!.items.map((i) => (
              <TR key={i.id} className="cursor-pointer" onClick={() => nav(`/investors/${i.id}`)}>
                <TD><div className="flex items-center gap-2 font-medium">{i.name}{i.do_not_contact && <Badge variant="destructive">DNC</Badge>}</div><div className="text-xs text-muted-foreground">{[i.title, i.firm].filter(Boolean).join(' · ')}</div></TD>
                <TD><div className="flex flex-wrap gap-1">{i.asset_classes.map((a) => <Badge key={a} variant={a === 'retail' ? 'accent' : 'default'} className="capitalize">{a}</Badge>)}</div><div className="mt-0.5 text-xs text-muted-foreground">{i.markets.join(', ')}</div></TD>
                <TD className="text-right tabular-nums">{compactMoney(i.min_check)} – {compactMoney(i.max_check)}</TD>
                <TD>{i.exchange_1031 ? <Badge variant={i.days_to_1031 != null && i.days_to_1031 < 60 ? 'destructive' : 'warning'}><Clock className="h-3 w-3" />{i.days_to_1031 != null ? `${i.days_to_1031}d` : 'Yes'}</Badge> : <span className="text-muted-foreground">—</span>}</TD>
                {showAcc && <TD><AccBadge s={i.accreditation_status} /></TD>}
                <TD className="text-right tabular-nums">{i.commitments ? compactMoney(Object.values(i.commitment_totals).reduce((a, b) => a + b, 0)) : '—'}</TD>
                <TD className="capitalize text-muted-foreground">{i.preferred_channel.replace('_', ' ')}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination page={page} limit={20} total={data!.total} onPage={setPage} />
        </>)}
      </Card>
    </div>
  )
}
