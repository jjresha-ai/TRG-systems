import { Link } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, CalendarClock, Flame, PhoneOff, Timer } from 'lucide-react'
import { useApi } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Loading, Stat } from '@/components/common'
import { BuildProgress } from '@/pages/Home'
import { compactMoney, num } from '@/lib/utils'

interface Dash {
  kpis: {
    ytd_closed_volume: number; ytd_closed_deals: number; ytd_listings_taken: number; ytd_gci?: number; active_listings: { count: number; value: number }; under_contract: { count: number; value: number }
    open_pipeline: { deals: number; volume: number; weighted_volume: number; weighted_commission?: number }; overdue_tasks: number; new_leads: number; hot_leads: number
    expiring_listings_60: number; stalled_deals: number; owners_untouched_90: number
  }
  goals: { metric: string; target: number; actual: number; pct: number }[]
  production_by_month: { group: string; closed_volume: number; gci?: number; listings_taken: number; closed_deals: number }[]
  pipeline_trend: { date: string; weighted_volume: number; weighted_commission?: number }[]
  top_leads: { id: number; name: string; score: number; address: string | null; city: string | null; reason: string | null }[]
  commission_visible: boolean
}

const GOAL_LABEL: Record<string, string> = { closed_volume: 'Closed volume', gci: 'GCI', listings_taken: 'Listings taken', closed_deals: 'Closed deals' }
const fmtGoal = (m: string, v: number) => (m === 'closed_volume' || m === 'gci' ? compactMoney(v) : num(v))

function GoalBar({ g }: { g: Dash['goals'][number] }) {
  return (
    <div data-testid="goal">
      <div className="mb-1 flex items-baseline justify-between text-sm"><span className="font-medium">{GOAL_LABEL[g.metric]}</span><span className="tabular-nums text-muted-foreground">{fmtGoal(g.metric, g.actual)} / {fmtGoal(g.metric, g.target)}</span></div>
      <div className="h-2.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-gradient-to-r from-accent to-[#e3b66a]" style={{ width: `${Math.min(g.pct, 100)}%` }} /></div>
      <div className="mt-0.5 text-right text-xs text-muted-foreground">{g.pct}%</div>
    </div>
  )
}

function Attention({ to, icon: I, n, label, tone }: { to: string; icon: typeof Timer; n: number; label: string; tone?: boolean }) {
  return (
    <Link to={to} className="flex items-center gap-3 rounded-lg border bg-background/60 p-3 hover:bg-secondary">
      <div className={`grid h-9 w-9 place-items-center rounded-full ${tone ? 'bg-destructive/12 text-destructive' : 'bg-accent/20 text-[#7a5614]'}`}><I className="h-4 w-4" /></div>
      <div><div className="font-display text-xl font-semibold leading-none">{n}</div><div className="text-xs text-muted-foreground">{label}</div></div>
    </Link>
  )
}

function DashboardView() {
  const { data: d, isLoading } = useApi<Dash>('/dashboard')
  if (isLoading || !d) return <Loading />
  const k = d.kpis
  const month = d.production_by_month.map((m) => ({ ...m, label: m.group.slice(5) }))
  const trend = d.pipeline_trend.map((t) => ({ ...t, label: t.date.slice(5), v: d.commission_visible ? t.weighted_commission : t.weighted_volume }))
  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="YTD closed volume" value={compactMoney(k.ytd_closed_volume)} hint={`${k.ytd_closed_deals} closed deals`} />
        {d.commission_visible ? <Stat label="YTD GCI" value={compactMoney(k.ytd_gci)} hint="gross commission" className="border-accent/50" /> : <Stat label="YTD GCI" value="Restricted" />}
        <Stat label="Active listings" value={k.active_listings.count} hint={compactMoney(k.active_listings.value)} />
        <Stat label="Under contract" value={k.under_contract.count} hint={compactMoney(k.under_contract.value)} />
        {d.commission_visible ? <Stat label="Weighted pipeline" value={compactMoney(k.open_pipeline.weighted_commission)} hint={`${k.open_pipeline.deals} open deals`} className="border-accent/50" /> : <Stat label="Weighted volume" value={compactMoney(k.open_pipeline.weighted_volume)} hint={`${k.open_pipeline.deals} open deals`} />}
        <Stat label="Listings taken YTD" value={k.ytd_listings_taken} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader className="pb-0"><CardTitle className="text-base">Closed volume by month (12 months)</CardTitle></CardHeader><CardContent className="h-56 pt-3">
          <ResponsiveContainer width="100%" height="100%"><BarChart data={month} margin={{ left: -8, right: 4 }}><CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis tickFormatter={(v) => compactMoney(v)} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} /><Tooltip formatter={(v) => compactMoney(Number(v))} cursor={{ fill: 'var(--muted)' }} /><Bar dataKey="closed_volume" name="Closed volume" fill="var(--primary)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
        </CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-base">{new Date().getFullYear()} goals</CardTitle></CardHeader><CardContent className="space-y-4">{d.goals.map((g) => <GoalBar key={g.metric} g={g} />)}{d.goals.length === 0 && <p className="text-sm text-muted-foreground">No goals set.</p>}</CardContent></Card>
        <Card className="lg:col-span-2"><CardHeader className="pb-0"><CardTitle className="text-base">{d.commission_visible ? 'Weighted commission' : 'Weighted volume'} in the pipeline (weekly snapshots)</CardTitle></CardHeader><CardContent className="h-52 pt-3">
          <ResponsiveContainer width="100%" height="100%"><AreaChart data={trend} margin={{ left: -8, right: 4 }}><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={0.5} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={24} /><YAxis tickFormatter={(v) => compactMoney(v)} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v) => compactMoney(Number(v))} /><Area type="monotone" dataKey="v" stroke="var(--accent)" strokeWidth={2} fill="url(#g)" /></AreaChart></ResponsiveContainer>
        </CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-base">Hottest new leads</CardTitle></CardHeader><CardContent><ul className="divide-y">{d.top_leads.map((l) => (
          <li key={l.id} className="flex items-center gap-3 py-2"><Badge variant="accent" className="w-10 justify-center">{l.score}</Badge><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{l.name}</div><div className="truncate text-xs text-muted-foreground">{l.address ? `${l.address}, ${l.city}` : l.reason}</div></div></li>))}</ul>
          <Link to="/prospecting" className="mt-2 block text-sm text-primary hover:underline">Open prospecting board →</Link></CardContent></Card>
      </div>
      <h2 className="mb-2 mt-6 font-display text-xl font-semibold">Needs attention</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Attention to="/tasks" icon={AlertTriangle} n={k.overdue_tasks} label="your overdue tasks" tone={k.overdue_tasks > 0} />
        <Attention to="/prospecting" icon={Flame} n={k.hot_leads} label="hot new leads (60+)" />
        <Attention to="/listings" icon={CalendarClock} n={k.expiring_listings_60} label="listings expiring in 60 days" tone={k.expiring_listings_60 > 0} />
        <Attention to="/deals" icon={Timer} n={k.stalled_deals} label="stalled deals" tone={k.stalled_deals > 0} />
        <Attention to="/reports" icon={PhoneOff} n={k.owners_untouched_90} label="owners untouched 90+ days" />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  return (
    <div className="rise">
      <PageHeader title={`Welcome, ${user?.name.split(' ')[0]}`} subtitle="The Resha Group · 1880 Capital" />
      <Tabs defaultValue="dashboard">
        <TabsList><TabsTrigger value="dashboard">Dashboard</TabsTrigger><TabsTrigger value="build">Build progress</TabsTrigger></TabsList>
        <TabsContent value="dashboard"><DashboardView /></TabsContent>
        <TabsContent value="build"><BuildProgress /></TabsContent>
      </Tabs>
    </div>
  )
}
