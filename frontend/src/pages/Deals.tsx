import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AlertTriangle, CalendarClock } from 'lucide-react'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Stat, Loading } from '@/components/common'
import { StageMoveDialog, needs, type DealLite, type StageLite } from '@/components/StageMove'
import { compactMoney, cn, fmtDate } from '@/lib/utils'
import { useSend } from '@/api/hooks'

export interface DealCard {
  id: number; name: string; price: number | null; status: string; probability: number; days_in_stage: number; rotting: boolean; owner_name: string | null
  expected_close_date: string | null; actual_close_date: string | null; weighted_commission?: number | null; gross_commission?: number | null; dd_expiry_date: string | null; lost_reason: string | null
  stage: StageLite & { rotting_days: number | null; probability: number }; property: { property_type: string; city: string } | null; pipeline: { key: string; name: string }
}
interface Column { stage: StageLite & { probability: number; rotting_days: number | null }; count: number; volume: number; deals: DealCard[]; weighted_commission?: number; commission?: number }
interface Board { pipeline: { id: number; key: string; name: string }; columns: Column[] }
interface Forecast { totals: { count: number; volume: number; weighted_volume: number; commission?: number; weighted_commission?: number }; by_month: { month: string; weighted_volume: number; weighted_commission?: number; count: number }[]; commission_visible: boolean }

const PIPES = [['seller', 'Seller-side'], ['buyer', 'Buyer rep'], ['capital', 'Capital'], ['leasing', 'Leasing']]
const initials = (n: string | null) => (n ?? '?').split(' ').map((s) => s[0]).join('').slice(0, 2)

export default function Deals() {
  const [pipe, setPipe] = useState('seller')
  const qc = useQueryClient()
  const board = useApi<Board>('/deals/board', { pipeline: pipe })
  const fc = useApi<Forecast>('/deals/forecast', { pipeline: pipe })
  const [drag, setDrag] = useState<DealCard | null>(null)
  const [over, setOver] = useState<number | null>(null)
  const [move, setMove] = useState<{ deal: DealCard; to: StageLite } | null>(null)
  const [err, setErr] = useState('')
  const quick = useSend<{ id: number; stage_id: number }>('POST', (b) => `/deals/${b.id}/stage`)
  const refresh = () => qc.invalidateQueries()
  const showComm = fc.data?.commission_visible

  const drop = (col: Column) => {
    setOver(null)
    if (!drag || drag.stage.id === col.stage.id) return
    setErr('')
    const n = needs(drag as unknown as DealLite, col.stage)
    if (n.price || n.lost || n.dd) return setMove({ deal: drag, to: col.stage })
    quick.mutate({ id: drag.id, stage_id: col.stage.id }, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) })
  }
  const total = fc.data?.totals
  return (
    <div className="rise">
      <PageHeader title="Deals" subtitle="Drag a deal between stages. The backend enforces the rules: price to close, reason to lose, dates for due diligence."
        actions={<Tabs value={pipe} onValueChange={setPipe}><TabsList>{PIPES.map(([k, l]) => <TabsTrigger key={k} value={k}>{l}</TabsTrigger>)}</TabsList></Tabs>} />
      <div className="mb-4 grid gap-4 lg:grid-cols-[1fr_2fr]">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Open deals" value={total?.count ?? '—'} />
          <Stat label="Open volume" value={compactMoney(total?.volume)} />
          <Stat label="Weighted volume" value={compactMoney(total?.weighted_volume)} />
          {showComm ? <Stat label="Weighted commission" value={compactMoney(total?.weighted_commission)} hint={`${compactMoney(total?.commission)} gross`} className="border-accent/50" /> : <Stat label="Commission" value="Restricted" />}
        </div>
        <Card><CardHeader className="pb-0"><CardTitle className="text-base">Forecast by expected close month <span className="text-xs font-normal text-muted-foreground">({showComm ? 'weighted commission' : 'weighted volume'})</span></CardTitle></CardHeader>
          <CardContent className="h-40 pt-2">
            <ResponsiveContainer width="100%" height="100%"><BarChart data={fc.data?.by_month.filter((m) => m.month !== 'unscheduled').slice(0, 12)} margin={{ left: -10, right: 4, top: 4 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="month" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} /><YAxis tickFormatter={(v) => compactMoney(v)} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v) => compactMoney(Number(v))} cursor={{ fill: 'var(--muted)' }} />
              <Bar dataKey={showComm ? 'weighted_commission' : 'weighted_volume'} fill="var(--accent)" radius={[4, 4, 0, 0]} />
            </BarChart></ResponsiveContainer>
          </CardContent></Card>
      </div>
      {err && <div role="alert" className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{err}</div>}
      {board.isLoading ? <Loading /> : (
        <div className="flex gap-3 overflow-x-auto pb-4" data-testid="board">
          {board.data?.columns.map((col) => (
            <div key={col.stage.id} data-testid={`stage-${col.stage.key}`} onDragOver={(e) => { e.preventDefault(); setOver(col.stage.id) }} onDragLeave={() => setOver(null)} onDrop={() => drop(col)}
              className={cn('w-72 shrink-0 rounded-xl bg-muted/70 p-2.5 transition-colors', over === col.stage.id && 'bg-accent/20 ring-2 ring-accent')}>
              <div className="mb-2 px-1.5">
                <div className="flex items-center justify-between"><h3 className="font-display text-sm font-semibold">{col.stage.name}</h3><Badge variant="outline">{col.count}</Badge></div>
                <div className="text-xs text-muted-foreground">{compactMoney(col.volume)}{showComm && col.weighted_commission != null && !col.stage.is_won ? ` · ${compactMoney(col.weighted_commission)} wtd` : ''} · {col.stage.probability}%</div>
              </div>
              <div className="max-h-[60vh] space-y-2 overflow-y-auto">
                {col.deals.map((d) => (
                  <Link key={d.id} to={`/deals/${d.id}`} draggable onDragStart={() => setDrag(d)} onDragEnd={() => setDrag(null)} data-testid="deal-card"
                    className="block cursor-grab rounded-lg border bg-card p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing">
                    <div className="line-clamp-2 text-sm font-medium leading-snug">{d.name}</div>
                    <div className="mt-1 flex items-baseline justify-between"><span className="font-display text-lg font-semibold">{compactMoney(d.price)}</span>
                      {showComm && d.gross_commission != null && <span className="text-xs text-muted-foreground">{compactMoney(d.gross_commission)} fee</span>}</div>
                    <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                      <span className="flex items-center gap-1"><span className="grid h-5 w-5 place-items-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground">{initials(d.owner_name)}</span>
                        {d.expected_close_date ? <><CalendarClock className="h-3 w-3" />{fmtDate(d.expected_close_date)}</> : d.actual_close_date ? fmtDate(d.actual_close_date) : ''}</span>
                      {d.rotting ? <Badge variant="destructive" className="gap-1"><AlertTriangle className="h-3 w-3" />{d.days_in_stage}d</Badge> : <span>{d.days_in_stage}d</span>}
                    </div>
                  </Link>))}
                {col.count > col.deals.length && <p className="px-1 text-xs text-muted-foreground">+ {col.count - col.deals.length} more</p>}
                {col.count === 0 && <p className="px-1 py-6 text-center text-xs text-muted-foreground">Drop a deal here</p>}
              </div>
            </div>))}
        </div>)}
      <StageMoveDialog deal={move?.deal as unknown as DealLite ?? null} to={move?.to ?? null} onClose={() => setMove(null)} onDone={refresh} />
    </div>
  )
}
