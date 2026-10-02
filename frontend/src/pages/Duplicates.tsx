import { useState } from 'react'
import { GitMerge, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useApi, useSend } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ErrorBox, Loading } from '@/components/common'

interface Rec { id: number; full_name?: string; name?: string; address?: string; title?: string | null; company?: string | null; primary_email?: string | null; city?: string | null; kind?: string }
interface Item { id: number; entity: string; reason: string; a: Rec; b: Rec }

const label = (r: Rec) => r.full_name ?? r.name ?? r.address ?? `#${r.id}`
const sub = (r: Rec) => [r.title, r.company, r.primary_email, r.kind, r.city].filter(Boolean).join(' · ')

export default function Duplicates() {
  const { data, isLoading, error } = useApi<{ items: Item[] }>('/duplicates', { status: 'pending' })
  const merges = useApi<{ items: { id: number; entity: string; survivor_id: number; absorbed_id: number; undone_at: string | null }[] }>('/merges')
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const refresh = () => qc.invalidateQueries()
  const merge = useSend<{ entity: string; survivor_id: number; absorbed_id: number }>('POST', '/merge')
  const dismiss = useSend<number>('POST', (id) => `/duplicates/${id}/dismiss`)
  const undo = useSend<number>('POST', (id) => `/merges/${id}/undo`)

  return (
    <div className="rise">
      <PageHeader title="Data Quality" subtitle="Possible duplicates are queued for review. Merging moves every association to the surviving record and can be undone." />
      {msg && <div className="mb-4 rounded-md border border-success/30 bg-success/10 p-3 text-sm text-success">{msg}</div>}
      {isLoading ? <Loading /> : error ? <ErrorBox error={error} /> : data!.items.length === 0 ? <Card><CardContent className="py-10 text-center text-muted-foreground">No pending duplicates.</CardContent></Card> : (
        <div className="space-y-3">{data!.items.map((d) => (
          <Card key={d.id}><CardContent className="grid items-center gap-4 pt-5 md:grid-cols-[1fr_auto_1fr_auto]">
            <div><Badge variant="outline" className="mb-1 capitalize">{d.entity}</Badge><div className="font-medium">{label(d.a)}</div><div className="text-xs text-muted-foreground">{sub(d.a)}</div></div>
            <Badge variant="warning">{d.reason}</Badge>
            <div><div className="font-medium">{label(d.b)}</div><div className="text-xs text-muted-foreground">{sub(d.b)}</div></div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => merge.mutate({ entity: d.entity, survivor_id: d.a.id, absorbed_id: d.b.id }, { onSuccess: () => { setMsg(`Merged ${label(d.b)} into ${label(d.a)}.`); refresh() } })}><GitMerge className="h-4 w-4" /> Keep first</Button>
              <Button size="sm" variant="outline" onClick={() => merge.mutate({ entity: d.entity, survivor_id: d.b.id, absorbed_id: d.a.id }, { onSuccess: () => { setMsg(`Merged ${label(d.a)} into ${label(d.b)}.`); refresh() } })}>Keep second</Button>
              <Button size="sm" variant="ghost" aria-label="Dismiss" onClick={() => dismiss.mutate(d.id, { onSuccess: refresh })}><X className="h-4 w-4" /></Button>
            </div>
          </CardContent></Card>))}
        </div>)}
      <h2 className="mb-2 mt-8 font-display text-xl font-semibold">Recent merges</h2>
      <Card><CardContent className="pt-5"><ul className="divide-y text-sm">
        {merges.data?.items.length === 0 && <li className="text-muted-foreground">No merges yet.</li>}
        {merges.data?.items.map((m) => (<li key={m.id} className="flex items-center justify-between py-2"><span className="capitalize">{m.entity} #{m.absorbed_id} → #{m.survivor_id}</span>
          {m.undone_at ? <Badge variant="secondary">Undone</Badge> : <Button size="sm" variant="outline" onClick={() => undo.mutate(m.id, { onSuccess: () => { setMsg('Merge undone.'); refresh() } })}>Undo</Button>}</li>))}
      </ul></CardContent></Card>
    </div>
  )
}
