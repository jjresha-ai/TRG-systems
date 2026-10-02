import { Plus, Trash2 } from 'lucide-react'
import { useUsers } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'

export interface FieldMeta { key: string; label: string; type: string; operators: string[]; options: string[]; group: string; multi: boolean }
export interface Cond { field: string; operator: string; value?: unknown }
export interface Group { op: 'and' | 'or'; conditions: (Cond | Group)[] }
export const isGroup = (n: Cond | Group): n is Group => 'conditions' in n

const NO_VALUE = new Set(['is_null', 'not_null', 'is_empty', 'not_empty'])
const OP_LABEL: Record<string, string> = {
  eq: 'is', ne: 'is not', gt: '>', gte: '≥', lt: '<', lte: '≤', between: 'between', in: 'is one of', contains: 'contains', starts_with: 'starts with', not_contains: 'does not contain',
  is_null: 'is empty', not_null: 'is not empty', is_empty: 'has none', not_empty: 'has any', within_days: 'is within next (days)', older_than_days: 'is older than (days)',
}
export const opLabel = (o: string) => OP_LABEL[o] ?? o

function ValueInput({ f, c, onChange }: { f: FieldMeta; c: Cond; onChange: (v: unknown) => void }) {
  const users = useUsers()
  const op = c.operator
  if (NO_VALUE.has(op)) return null
  const num = f.type === 'number' || f.type === 'money'
  const cast = (s: string) => (num ? (s === '' ? '' : Number(s)) : s)
  if (op === 'between') {
    const v = (c.value as unknown[]) ?? ['', '']
    const t = f.type === 'date' ? 'date' : 'number'
    return <div className="flex items-center gap-1"><Input type={t} aria-label="From" className="w-32" value={String(v[0] ?? '')} onChange={(e) => onChange([t === 'number' ? Number(e.target.value) : e.target.value, v[1]])} />
      <span className="text-xs text-muted-foreground">and</span><Input type={t} aria-label="To" className="w-32" value={String(v[1] ?? '')} onChange={(e) => onChange([v[0], t === 'number' ? Number(e.target.value) : e.target.value])} /></div>
  }
  if (op === 'in') return <Input aria-label="Values" className="w-56" placeholder="comma, separated" value={Array.isArray(c.value) ? (c.value as unknown[]).join(', ') : ''} onChange={(e) => onChange(e.target.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => (num ? Number(x) : x)))} />
  if (op === 'within_days' || op === 'older_than_days') return <Input type="number" aria-label="Days" className="w-28" value={String(c.value ?? '')} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
  if (f.type === 'bool') return <Select aria-label="Value" value={String(c.value ?? 'true')} onChange={(e) => onChange(e.target.value === 'true')}><option value="true">Yes</option><option value="false">No</option></Select>
  if (f.type === 'user') return <Select aria-label="Value" value={String(c.value ?? '')} onChange={(e) => onChange(Number(e.target.value))}><option value="">Choose…</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select>
  if (f.options.length && f.type !== 'list') return <Select aria-label="Value" value={String(c.value ?? '')} onChange={(e) => onChange(e.target.value)}><option value="">Choose…</option>{f.options.map((o) => <option key={o}>{o}</option>)}</Select>
  if (f.type === 'date') return <Input type="date" aria-label="Value" className="w-40" value={String(c.value ?? '')} onChange={(e) => onChange(e.target.value)} />
  return <Input type={num ? 'number' : 'text'} aria-label="Value" list={f.options.length ? `opts-${f.key}` : undefined} className="w-48" value={String(c.value ?? '')} onChange={(e) => onChange(cast(e.target.value))} />
}

function CondRow({ fields, c, onChange, onRemove }: { fields: FieldMeta[]; c: Cond; onChange: (c: Cond) => void; onRemove: () => void }) {
  const f = fields.find((x) => x.key === c.field) ?? fields[0]
  const groups = [...new Set(fields.map((x) => x.group))]
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="condition">
      <Select aria-label="Field" value={c.field} className="w-52" onChange={(e) => { const nf = fields.find((x) => x.key === e.target.value)!; onChange({ field: nf.key, operator: nf.operators[0], value: undefined }) }}>
        {groups.map((g) => <optgroup key={g} label={g}>{fields.filter((x) => x.group === g).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</optgroup>)}</Select>
      <Select aria-label="Operator" value={c.operator} onChange={(e) => onChange({ ...c, operator: e.target.value, value: undefined })}>{f.operators.map((o) => <option key={o} value={o}>{opLabel(o)}</option>)}</Select>
      <ValueInput f={f} c={c} onChange={(v) => onChange({ ...c, value: v })} />
      {f.options.length > 0 && f.type === 'list' && <datalist id={`opts-${f.key}`}>{f.options.map((o) => <option key={o} value={o} />)}</datalist>}
      <Button size="icon" variant="ghost" aria-label="Remove condition" onClick={onRemove}><Trash2 className="h-4 w-4" /></Button>
    </div>
  )
}

export function GroupEditor({ fields, g, onChange, depth = 0, onRemove }: { fields: FieldMeta[]; g: Group; onChange: (g: Group) => void; depth?: number; onRemove?: () => void }) {
  const set = (i: number, n: Cond | Group) => onChange({ ...g, conditions: g.conditions.map((x, j) => (j === i ? n : x)) })
  const del = (i: number) => onChange({ ...g, conditions: g.conditions.filter((_, j) => j !== i) })
  const newCond = (): Cond => ({ field: fields[0].key, operator: fields[0].operators[0] })
  return (
    <div className={depth ? 'rounded-lg border bg-muted/40 p-3' : ''}>
      <div className="mb-2 flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Match</span>
        <Select aria-label={depth ? 'Group operator' : 'Match operator'} value={g.op} onChange={(e) => onChange({ ...g, op: e.target.value as 'and' | 'or' })} className="h-8"><option value="and">all of</option><option value="or">any of</option></Select>
        <span className="text-muted-foreground">these conditions</span>
        {onRemove && <Button size="sm" variant="ghost" onClick={onRemove}>Remove group</Button>}
      </div>
      <div className="space-y-2">{g.conditions.map((n, i) => isGroup(n)
        ? <GroupEditor key={i} fields={fields} g={n} depth={depth + 1} onChange={(x) => set(i, x)} onRemove={() => del(i)} />
        : <CondRow key={i} fields={fields} c={n} onChange={(x) => set(i, x)} onRemove={() => del(i)} />)}</div>
      <div className="mt-2 flex gap-2">
        <Button size="sm" variant="outline" onClick={() => onChange({ ...g, conditions: [...g.conditions, newCond()] })}><Plus className="h-3.5 w-3.5" /> Condition</Button>
        {depth < 2 && <Button size="sm" variant="ghost" onClick={() => onChange({ ...g, conditions: [...g.conditions, { op: 'or', conditions: [newCond()] }] })}><Plus className="h-3.5 w-3.5" /> Group</Button>}
      </div>
    </div>
  )
}

/** Drop incomplete conditions so the live preview never sends a half-built filter. */
export function clean(g: Group): Group {
  const conds = g.conditions.map((n) => (isGroup(n) ? clean(n) : n)).filter((n) => {
    if (isGroup(n)) return n.conditions.length > 0
    if (NO_VALUE.has(n.operator)) return true
    const v = n.value
    return v !== undefined && v !== '' && !(Array.isArray(v) && (v.length === 0 || v.some((x) => x === '' || Number.isNaN(x))))
  })
  return { ...g, conditions: conds }
}
