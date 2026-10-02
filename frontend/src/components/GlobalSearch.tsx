import { useQuery } from '@tanstack/react-query'
import { Building2, MapPin, Search, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { Badge } from '@/components/ui/badge'

interface Result { type: string; id: number; title: string; subtitle: string; url: string; connections: string[] }
const ICON: Record<string, typeof User> = { contact: User, company: Building2, property: MapPin }

export function GlobalSearch() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 180); return () => clearTimeout(t) }, [q])
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const { data } = useQuery({ queryKey: ['search', debounced], queryFn: () => api<{ results: Result[] }>('/search', { params: { q: debounced, limit: 12 } }), enabled: debounced.length >= 2 })
  const go = (r: Result) => { setOpen(false); setQ(''); nav(r.url) }

  return (
    <div ref={ref} className="relative w-full max-w-lg">
      <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
      <input aria-label="Global search" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
        placeholder="Search owners, entities, properties, APN, phone, email…"
        className="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      {open && debounced.length >= 2 && (
        <div role="listbox" className="absolute z-40 mt-1 max-h-[70vh] w-full min-w-[26rem] overflow-y-auto rounded-lg border bg-card shadow-xl">
          {data?.results.length === 0 && <div className="p-4 text-sm text-muted-foreground">No matches for “{debounced}”.</div>}
          {data?.results.map((r) => {
            const I = ICON[r.type] ?? User
            return (
              <button key={`${r.type}-${r.id}`} role="option" onClick={() => go(r)} className="flex w-full cursor-pointer items-start gap-3 border-b px-4 py-2.5 text-left last:border-0 hover:bg-secondary">
                <I className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="truncate font-medium">{r.title}</span><Badge variant="outline" className="capitalize">{r.type}</Badge></div>
                  <div className="truncate text-xs text-muted-foreground">{r.subtitle}</div>
                  {r.connections.length > 0 && <div className="truncate text-xs text-accent/90">↔ {r.connections.slice(0, 3).join(' · ')}</div>}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
