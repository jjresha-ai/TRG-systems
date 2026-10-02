import { useLocation } from 'react-router-dom'
import { Hammer } from 'lucide-react'
import { NAV } from '@/nav'
import { useProgress } from '@/api/progress'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'

export default function ComingSoon() {
  const { pathname } = useLocation()
  const item = NAV.find((n) => n.to === pathname)
  const { data } = useProgress()
  const stage = data?.stages.find((s) => s.id === item?.stage)
  return (
    <div className="rise">
      <PageHeader title={item?.label ?? 'Not found'} subtitle={stage?.blurb} />
      <div className="grid place-items-center rounded-xl border border-dashed bg-card/60 py-24 text-center">
        <Hammer className="mb-4 h-10 w-10 text-accent" />
        <h2 className="font-display text-2xl">Coming soon</h2>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          {stage ? `Being built in Stage ${stage.id}: ${stage.name}. The backend ships first with passing tests, then this screen appears here automatically.` : 'This page does not exist.'}
        </p>
        {stage && <div className="mt-4 flex gap-2"><Badge variant="outline">Backend: {stage.backend}</Badge><Badge variant="outline">Screen: {stage.frontend}</Badge></div>}
      </div>
    </div>
  )
}
