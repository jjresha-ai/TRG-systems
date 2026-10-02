import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { useApi, useSend } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ErrorBox } from '@/components/common'
import { fmtDate } from '@/lib/utils'

interface Def { id: number; key: string; label: string; type: string; options: string[]; required: boolean; restricted: boolean }

const show = (d: Def, v: unknown) => {
  if (v === undefined || v === null || v === '') return <span className="text-muted-foreground">—</span>
  if (d.type === 'checkbox') return v ? 'Yes' : 'No'
  if (d.type === 'date') return fmtDate(String(v))
  if (d.type === 'currency') return `$${Number(v).toLocaleString()}`
  if (Array.isArray(v)) return v.map((x) => <Badge key={String(x)} variant="secondary" className="mr-1">{String(x)}</Badge>)
  return String(v)
}

/** Renders and edits custom fields for any entity. The backend validates every value (ADR 0019). */
export function CustomFieldsCard({ entity, path, values }: { entity: string; path: string; values: Record<string, unknown> }) {
  const defs = useApi<{ items: Def[] }>('/custom-fields', { entity })
  const qc = useQueryClient()
  const [edit, setEdit] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [err, setErr] = useState('')
  const save = useSend<{ custom: object }>('PATCH', path)
  if (!defs.data || defs.data.items.length === 0) return null
  const start = () => { setDraft({ ...values }); setEdit(true); setErr('') }
  const input = (d: Def) => {
    const v = draft[d.key]
    const set = (x: unknown) => setDraft({ ...draft, [d.key]: x })
    if (d.type === 'checkbox') return <input type="checkbox" aria-label={d.label} checked={!!v} onChange={(e) => set(e.target.checked)} />
    if (d.type === 'single_select') return <Select aria-label={d.label} value={String(v ?? '')} onChange={(e) => set(e.target.value || null)}><option value="">—</option>{d.options.map((o) => <option key={o}>{o}</option>)}</Select>
    if (d.type === 'multi_select') return <div className="flex flex-wrap gap-2">{d.options.map((o) => <label key={o} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={((v as string[]) ?? []).includes(o)} onChange={(e) => set(e.target.checked ? [...((v as string[]) ?? []), o] : ((v as string[]) ?? []).filter((x) => x !== o))} />{o}</label>)}</div>
    const t = d.type === 'number' || d.type === 'currency' ? 'number' : d.type === 'date' ? 'date' : 'text'
    return <Input aria-label={d.label} type={t} value={String(v ?? '')} onChange={(e) => set(e.target.value === '' ? null : t === 'number' ? Number(e.target.value) : e.target.value)} />
  }
  return (
    <Card data-testid="custom-fields"><CardHeader><div className="flex items-center justify-between"><CardTitle>Custom fields</CardTitle>
      {!edit && <Button size="sm" variant="outline" onClick={start}><Pencil className="h-3.5 w-3.5" /> Edit</Button>}</div></CardHeader>
      <CardContent className="space-y-2.5 text-sm">
        {defs.data.items.map((d) => (<div key={d.key} className="flex items-start justify-between gap-3"><span className="pt-1.5 text-muted-foreground">{d.label}{d.required && ' *'}{d.restricted && ' 🔒'}</span><span className="text-right font-medium">{edit ? input(d) : show(d, values?.[d.key])}</span></div>))}
        {err && <ErrorBox error={new Error(err)} />}
        {edit && <div className="flex gap-2 pt-2"><Button size="sm" onClick={() => save.mutate({ custom: Object.fromEntries(defs.data!.items.map((d) => [d.key, draft[d.key] === undefined ? null : draft[d.key]]).filter(([k, v]) => v !== null || values?.[k as string] !== undefined)) }, { onSuccess: () => { setEdit(false); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) })}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button></div>}
      </CardContent></Card>
  )
}
