import { useState } from 'react'
import { Download } from 'lucide-react'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { ErrorBox, Loading } from '@/components/common'
import { cn, compactMoney, fmtDate, num } from '@/lib/utils'
import { getToken } from '@/api/client'
import { useAuth } from '@/api/auth'

interface Rep { columns: string[]; rows: Record<string, unknown>[]; totals?: Record<string, number>; goals?: { metric: string; target: number; actual: number; pct: number }[]; stalled?: Record<string, unknown>[]; expiring?: Record<string, unknown>[]; activity_by_user?: Record<string, unknown>[]; total?: number; period?: { start: string; end: string } }

const CATALOG = [
  { key: 'production', label: 'Production', path: '/reports/production', blurb: 'Listings taken and closed deals, volume and GCI by broker, month or property type' },
  { key: 'pipeline', label: 'Pipeline & forecast', path: '/reports/pipeline', blurb: 'Open deals weighted by stage probability' },
  { key: 'listings', label: 'Listings', path: '/reports/listings', blurb: 'Status, days on market, expirations' },
  { key: 'buyer', label: 'Buyer interest', path: '/reports/buyer-interest', blurb: 'Inquiries, CAs, OMs, tours and offers per listing' },
  { key: 'prospecting', label: 'Prospecting', path: '/reports/prospecting', blurb: 'Lead sources, conversion, activity per broker' },
  { key: 'recency', label: 'Owner recency', path: '/reports/owner-recency', blurb: 'Owners not touched in 90+ days' },
  { key: 'tis', label: 'Time in stage', path: '/reports/time-in-stage', blurb: 'Where deals wait; stalled deals' },
  { key: 'capital', label: 'Investor capital', path: '/reports/investor-capital', blurb: 'Capital raised by fund and commitment status' },
]
const MONEY = new Set(['closed_volume', 'gci', 'volume', 'weighted_volume', 'commission', 'weighted_commission', 'value', 'list_price', 'best_offer', 'target_raise', 'interested', 'soft_circled', 'committed', 'funded', 'committed_or_funded'])
const PCT = new Set(['conversion_rate', 'pct_of_target'])
const DATES = new Set(['last_contact_at', 'expires'])

const cell = (c: string, v: unknown) => {
  if (v == null) return '—'
  if (MONEY.has(c)) return compactMoney(Number(v))
  if (PCT.has(c)) return `${v}%`
  if (DATES.has(c)) return fmtDate(String(v))
  if (typeof v === 'number') return num(v)
  return String(v)
}
const head = (c: string) => c.replace(/_/g, ' ')

export function ReportTable({ rep, testid }: { rep: Pick<Rep, 'columns' | 'rows'>; testid?: string }) {
  return (
    <Table data-testid={testid}><THead><TR>{rep.columns.map((c) => <TH key={c} className={cn(typeof rep.rows[0]?.[c] === 'number' && 'text-right')}>{head(c)}</TH>)}</TR></THead>
      <TBody>{rep.rows.map((r, i) => <TR key={i}>{rep.columns.map((c) => <TD key={c} className={cn(typeof r[c] === 'number' && 'text-right tabular-nums', c === 'group' || c === 'name' || c === 'fund' || c === 'address' ? 'font-medium' : '')}>{cell(c, r[c])}</TD>)}</TR>)}
        {rep.rows.length === 0 && <TR><TD colSpan={rep.columns.length} className="py-8 text-center text-muted-foreground">No rows for these filters.</TD></TR>}</TBody></Table>
  )
}

export default function Reports() {
  const { user } = useAuth()
  const [sel, setSel] = useState(CATALOG[0])
  const [period, setPeriod] = useState('ytd')
  const [groupBy, setGroupBy] = useState('broker')
  const [pgroup, setPgroup] = useState('stage')
  const [pipe, setPipe] = useState('seller')
  const [days, setDays] = useState('90')
  const params: Record<string, unknown> = sel.key === 'production' ? { period, group_by: groupBy } : sel.key === 'pipeline' ? { group_by: pgroup } : sel.key === 'prospecting' ? { period } : sel.key === 'recency' ? { days } : sel.key === 'tis' ? { pipeline: pipe } : {}
  const { data, isLoading, error } = useApi<Rep>(sel.path, params)
  const canExport = user && ['admin', 'manager', 'broker'].includes(user.role)

  const download = async () => {
    const url = new URL(`/api${sel.path}`, window.location.origin)
    Object.entries({ ...params, format: 'csv' }).forEach(([k, v]) => v && url.searchParams.set(k, String(v)))
    const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } })
    if (!res.ok) return
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = `${sel.key}.csv`; a.click()
  }
  return (
    <div className="rise">
      <PageHeader title="Reports" subtitle="A fixed catalog of reports with filters and CSV export. Commission columns are hidden for roles without access." />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <nav className="space-y-1" aria-label="Report catalog">{CATALOG.map((c) => (
          <button key={c.key} onClick={() => setSel(c)} className={cn('w-full cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-colors', sel.key === c.key ? 'border-accent bg-accent/10' : 'bg-card hover:bg-secondary')}>
            <div className="text-sm font-semibold">{c.label}</div><div className="text-xs text-muted-foreground">{c.blurb}</div></button>))}</nav>
        <Card><div className="flex flex-wrap items-center gap-2 border-b p-4">
          <h2 className="mr-auto font-display text-xl font-semibold">{sel.label}</h2>
          {(sel.key === 'production' || sel.key === 'prospecting') && <Select aria-label="Period" value={period} onChange={(e) => setPeriod(e.target.value)}><option value="ytd">Year to date</option><option value="12m">Last 12 months</option><option value="quarter">This quarter</option><option value="month">This month</option></Select>}
          {sel.key === 'production' && <Select aria-label="Group by" value={groupBy} onChange={(e) => setGroupBy(e.target.value)}><option value="broker">By broker</option><option value="month">By month</option><option value="property_type">By property type</option></Select>}
          {sel.key === 'pipeline' && <Select aria-label="Group by" value={pgroup} onChange={(e) => setPgroup(e.target.value)}>{['stage', 'owner', 'property_type', 'market', 'close_month'].map((g) => <option key={g} value={g}>{`By ${g.replace('_', ' ')}`}</option>)}</Select>}
          {sel.key === 'recency' && <Input aria-label="Days" type="number" className="w-24" value={days} onChange={(e) => setDays(e.target.value)} />}
          {sel.key === 'tis' && <Select aria-label="Pipeline" value={pipe} onChange={(e) => setPipe(e.target.value)}>{['seller', 'buyer', 'capital', 'leasing'].map((p) => <option key={p}>{p}</option>)}</Select>}
          {canExport && <Button variant="outline" size="sm" onClick={download}><Download className="h-4 w-4" /> CSV</Button>}
        </div>
          <CardContent className="px-0 pt-0">{isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : data && (<>
            {data.total != null && <p className="px-4 pt-3 text-sm text-muted-foreground">{data.total} records match; showing the first {data.rows.length}.</p>}
            <ReportTable rep={data} testid="report-table" />
            {data.totals && <div className="flex flex-wrap gap-x-6 gap-y-1 border-t px-4 py-3 text-sm" data-testid="report-totals">{Object.entries(data.totals).map(([k, v]) => <span key={k}><span className="text-muted-foreground">{head(k)}:</span> <span className="font-semibold tabular-nums">{MONEY.has(k) ? compactMoney(v) : num(v)}</span></span>)}</div>}
            {data.goals && data.goals.length > 0 && <div className="border-t px-4 py-3 text-sm"><div className="mb-1 font-semibold">Goal progress</div><div className="flex flex-wrap gap-4">{data.goals.map((g) => <span key={g.metric}>{head(g.metric)}: <b>{g.pct}%</b></span>)}</div></div>}
            {data.stalled && data.stalled.length > 0 && <><h3 className="px-4 pt-4 font-display text-lg font-semibold">Stalled deals</h3><ReportTable rep={{ columns: ['name', 'stage', 'days_in_stage', 'rotting_days', 'owner'], rows: data.stalled }} /></>}
            {data.expiring && <><h3 className="px-4 pt-4 font-display text-lg font-semibold">Expiring listings</h3><ReportTable rep={{ columns: ['address', 'city', 'broker', 'expires', 'days_left', 'list_price'], rows: data.expiring }} /></>}
            {data.activity_by_user && <><h3 className="px-4 pt-4 font-display text-lg font-semibold">Activity by broker</h3><ReportTable rep={{ columns: ['user', 'calls', 'emails', 'meetings', 'site_visits', 'total'], rows: data.activity_by_user }} /></>}
          </>)}</CardContent></Card>
      </div>
    </div>
  )
}
