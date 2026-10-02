import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export const Loading = () => (
  <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
)

export const ErrorBox = ({ error }: { error: unknown }) => (
  <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{(error as Error)?.message ?? 'Something went wrong'}</div>
)

export function Pagination({ page, limit, total, onPage }: { page: number; limit: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit))
  return (
    <div className="flex items-center justify-between border-t px-4 py-3 text-sm text-muted-foreground">
      <span>{total === 0 ? 'No results' : `${(page - 1) * limit + 1}–${Math.min(page * limit, total)} of ${total.toLocaleString()}`}</span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="px-2">Page {page} / {pages}</span>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </div>
  )
}

export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardContent className="pt-4">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="mt-1 font-display text-2xl font-semibold">{value}</div>
        {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn('block text-sm', className)}>
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

export const TypeBadge = ({ t }: { t: string }) => {
  const v: Record<string, 'accent' | 'default' | 'success' | 'warning' | 'secondary'> = { owner: 'default', buyer: 'success', investor: 'accent', lender: 'warning' }
  return <Badge variant={v[t] ?? 'secondary'} className="capitalize">{t.replace('_', ' ')}</Badge>
}

export const HoldBadge = ({ h }: { h: string }) => {
  const m: Record<string, [string, 'secondary' | 'success' | 'warning' | 'destructive']> = {
    unknown: ['Unknown', 'secondary'], hold: ['Holding', 'success'], open_to_sell: ['Open to sell', 'warning'], selling_soon: ['Selling soon', 'destructive'],
  }
  const [t, v] = m[h] ?? m.unknown
  return <Badge variant={v}>{t}</Badge>
}

export const EntityLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className="font-medium text-primary underline-offset-2 hover:text-accent hover:underline">{children}</Link>
)

export function monthsUntil(d: string | null | undefined) {
  if (!d) return null
  const t = new Date(d).getTime() - Date.now()
  return Math.round(t / (30.44 * 86400000))
}

export const MaturityBadge = ({ d }: { d: string | null | undefined }) => {
  const m = monthsUntil(d)
  if (m == null) return <span className="text-muted-foreground">—</span>
  if (m < 0) return <Badge variant="destructive">Matured {-m} mo ago</Badge>
  if (m <= 12) return <Badge variant="destructive">{m} mo</Badge>
  if (m <= 24) return <Badge variant="warning">{m} mo</Badge>
  return <Badge variant="secondary">{m} mo</Badge>
}

export const ago = (s: string | null | undefined) => {
  if (!s) return 'Never'
  const d = Math.floor((Date.now() - new Date(s).getTime()) / 86400000)
  if (d < 1) return 'Today'
  if (d < 31) return `${d}d ago`
  if (d < 365) return `${Math.floor(d / 30)}mo ago`
  return `${(d / 365).toFixed(1)}y ago`
}
