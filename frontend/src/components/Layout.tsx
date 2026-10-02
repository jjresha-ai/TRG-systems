import { NavLink, Outlet, Navigate } from 'react-router-dom'
import { LogOut, Sparkles } from 'lucide-react'
import { useAuth } from '@/api/auth'
import { useProgress } from '@/api/progress'
import { NAV } from '@/nav'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { GlobalSearch } from '@/components/GlobalSearch'

export default function Layout() {
  const { user, logout } = useAuth()
  const { data } = useProgress()
  if (!user) return <Navigate to="/login" replace />
  const live = (stage: number) => stage === 0 || data?.stages.find((s) => s.id === stage)?.frontend === 'done'
  const groups = [...new Set(NAV.map((n) => n.group))]

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col bg-sidebar text-sidebar-foreground md:flex">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-accent font-display text-lg font-bold text-accent-foreground">T</div>
          <div className="leading-tight">
            <div className="font-display text-base text-white">TRG Systems</div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-sidebar-foreground/60">Resha Group</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {groups.map((g) => (
            <div key={g} className="mt-4">
              <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-sidebar-foreground/45">{g}</div>
              {NAV.filter((n) => n.group === g).map((n) => {
                const isLive = live(n.stage)
                return (
                  <NavLink key={n.to} to={n.to} end={n.to === '/'}
                    className={({ isActive }) => cn('flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
                      isActive ? 'bg-white/10 text-white' : 'hover:bg-white/5', !isLive && 'opacity-60')}>
                    <n.icon className="h-4 w-4" />
                    <span className="flex-1">{n.label}</span>
                    {!isLive && <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide">Soon</span>}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-white/10 p-4">
          <div className="text-sm font-medium text-white">{user.name}</div>
          <div className="mb-2 text-xs text-sidebar-foreground/60">{user.title}</div>
          <div className="flex items-center justify-between">
            <Badge variant="accent" className="capitalize">{user.role.replace('_', ' ')}</Badge>
            <button onClick={logout} aria-label="Sign out" className="cursor-pointer rounded p-1.5 hover:bg-white/10"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-4 border-b bg-card/70 px-6 py-3 backdrop-blur">
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <span className="live-dot h-2 w-2 rounded-full bg-accent" /> <Sparkles className="h-3.5 w-3.5" /> Live build in progress
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6 md:p-8"><Outlet /></main>
      </div>
    </div>
  )
}
