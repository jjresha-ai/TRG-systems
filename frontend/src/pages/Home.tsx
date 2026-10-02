import { CheckCircle2, Circle, Loader2, Server, MonitorSmartphone } from 'lucide-react'
import { useProgress, type Stage } from '@/api/progress'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function Status({ s, icon: Icon, label }: { s: string; icon: typeof Server; label: string }) {
  const map: Record<string, { cls: string; text: string; I: typeof Circle }> = {
    done: { cls: 'text-success', text: 'Done · tests passing', I: CheckCircle2 },
    building: { cls: 'text-accent', text: 'Building now', I: Loader2 },
    next: { cls: 'text-warning', text: 'Up next', I: Circle },
    soon: { cls: 'text-muted-foreground', text: 'Coming soon', I: Circle },
  }
  const m = map[s] ?? map.soon
  return (
    <div className={cn('flex items-center gap-2 text-sm', m.cls)}>
      <Icon className="h-4 w-4" /> <span className="w-16 font-medium text-foreground/80">{label}</span>
      <m.I className={cn('h-4 w-4', s === 'building' && 'animate-spin')} /> <span>{m.text}</span>
    </div>
  )
}

function StageCard({ s }: { s: Stage }) {
  const done = s.backend === 'done' && s.frontend === 'done'
  const active = s.backend === 'building' || s.frontend === 'building'
  return (
    <Card className={cn('rise', active && 'ring-2 ring-accent', done && 'bg-card')}>
      <CardContent className="pt-5">
        <div className="flex items-start justify-between">
          <div className="font-display text-4xl font-semibold text-accent/80">{s.id}</div>
          <div className="text-right text-[11px] uppercase tracking-wider text-muted-foreground">ADR {s.adrs}</div>
        </div>
        <h3 className="mt-1 font-display text-lg font-semibold">{s.name}</h3>
        <p className="mb-4 text-sm text-muted-foreground">{s.blurb}</p>
        <div className="space-y-1.5">
          <Status s={s.backend} icon={Server} label="Backend" />
          <Status s={s.frontend} icon={MonitorSmartphone} label="Screens" />
        </div>
      </CardContent>
    </Card>
  )
}

export function BuildProgress() {
  const { data } = useProgress()
  const stages = data?.stages ?? []
  const total = stages.length * 2
  const done = stages.reduce((n, s) => n + (s.backend === 'done' ? 1 : 0) + (s.frontend === 'done' ? 1 : 0), 0)
  const pct = total ? Math.round((done / total) * 100) : 0

  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">This CRM is being built live, in stages: backend first with passing tests, then the screens. Refreshes every few seconds.</p>
      <Card className="mb-6 overflow-hidden">
        <CardContent className="pt-5">
          <div className="mb-2 flex items-end justify-between">
            <div><div className="font-display text-5xl font-semibold">{pct}%</div><div className="text-sm text-muted-foreground">of the build complete</div></div>
            <div className="text-right text-sm text-muted-foreground">{done} of {total} milestones</div>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-gradient-to-r from-accent to-[#e3b66a] transition-all duration-1000" style={{ width: `${pct}%` }} /></div>
        </CardContent>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{stages.map((s) => <StageCard key={s.id} s={s} />)}</div>
    </div>
  )
}
