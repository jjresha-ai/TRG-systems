import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, Save, Tag, Trash2 } from 'lucide-react'
import { api } from '@/api/client'
import { useApi, useSend } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading, Pagination } from '@/components/common'
import { GroupEditor, clean, type FieldMeta, type Group } from '@/components/FilterBuilder'
import { compactMoney, fmtDate } from '@/lib/utils'

const ENTITIES = [['property', 'Properties'], ['contact', 'Contacts'], ['company', 'Companies'], ['listing', 'Listings'], ['deal', 'Deals'], ['lead', 'Leads']]
interface QS { entity: string; filter: Group; columns?: string[]; sort_field?: string; sort_dir: 'asc' | 'desc' }
interface Result { total: number; columns: { key: string; label: string; type: string }[]; items: (Record<string, unknown> & { id: number; label: string; url: string })[] }
const EMPTY: Group = { op: 'and', conditions: [] }

const fmt = (type: string, v: unknown) => {
  if (v === null || v === undefined || v === '') return '—'
  if (type === 'money') return compactMoney(Number(v))
  if (type === 'date') return fmtDate(String(v))
  if (type === 'bool') return v ? 'Yes' : 'No'
  return String(v)
}

export default function Lists() {
  const [tab, setTab] = useState('builder')
  const [qs, setQs] = useState<QS>({ entity: 'property', filter: EMPTY, sort_dir: 'asc' })
  const load = (next: Partial<QS>) => { setQs({ entity: 'property', filter: EMPTY, sort_dir: 'asc', ...next }); setTab('builder') }
  return (
    <div className="rise">
      <PageHeader title="Lists & Views" subtitle="One filter builder powers saved views, call lists and campaigns. Related records count: owners whose properties have loans maturing, and so on." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList><TabsTrigger value="builder">Query builder</TabsTrigger><TabsTrigger value="views">Saved views</TabsTrigger><TabsTrigger value="lists">Lists</TabsTrigger><TabsTrigger value="tags">Tags</TabsTrigger><TabsTrigger value="fields">Custom fields</TabsTrigger></TabsList>
        <TabsContent value="builder"><Builder qs={qs} setQs={setQs} /></TabsContent>
        <TabsContent value="views"><Views onOpen={(v) => load({ entity: v.entity, filter: v.filter as Group, columns: v.columns.length ? v.columns : undefined, sort_field: v.sort_field ?? undefined, sort_dir: (v.sort_dir as 'asc' | 'desc') ?? 'asc' })} /></TabsContent>
        <TabsContent value="lists"><ListsTab onOpen={(l) => l.filter && load({ entity: l.entity, filter: l.filter as Group })} /></TabsContent>
        <TabsContent value="tags"><Tags onPick={(entity, tag) => load({ entity, filter: { op: 'and', conditions: [{ field: 'tags', operator: 'contains', value: tag }] } })} /></TabsContent>
        <TabsContent value="fields"><CustomFields /></TabsContent>
      </Tabs>
    </div>
  )
}

function Builder({ qs, setQs }: { qs: QS; setQs: (q: QS) => void }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const meta = useApi<{ fields: FieldMeta[] }>('/filter-fields', { entity: qs.entity })
  const [page, setPage] = useState(1)
  const [sel, setSel] = useState<number[]>([])
  const cleaned = clean(qs.filter)
  useEffect(() => setPage(1), [qs.entity, JSON.stringify(cleaned), qs.sort_field, qs.sort_dir])
  const res = useQuery({ queryKey: ['query', qs.entity, cleaned, qs.columns, qs.sort_field, qs.sort_dir, page], queryFn: () => api<Result>('/query', { method: 'POST', body: { entity: qs.entity, filter: cleaned, columns: qs.columns, sort_field: qs.sort_field, sort_dir: qs.sort_dir, page, limit: 15 } }), placeholderData: (p) => p })
  const fields = meta.data?.fields ?? []
  const taggable = ['contact', 'company', 'property', 'listing', 'deal'].includes(qs.entity)
  return (
    <div className="space-y-4">
      <Card><CardContent className="pt-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select aria-label="Entity" value={qs.entity} onChange={(e) => { setQs({ entity: e.target.value, filter: EMPTY, sort_dir: 'asc' }); setSel([]) }}>{ENTITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
          {fields.length > 0 && <Select aria-label="Sort by" value={qs.sort_field ?? ''} onChange={(e) => setQs({ ...qs, sort_field: e.target.value || undefined })}><option value="">Sort: default</option>{fields.map((f) => <option key={f.key} value={f.key}>{`Sort: ${f.label}`}</option>)}</Select>}
          <Select aria-label="Sort direction" value={qs.sort_dir} onChange={(e) => setQs({ ...qs, sort_dir: e.target.value as 'asc' | 'desc' })}><option value="asc">Ascending</option><option value="desc">Descending</option></Select>
          <div className="ml-auto flex gap-2"><SaveView qs={qs} cleaned={cleaned} /><SaveList qs={qs} cleaned={cleaned} />{taggable && <TagSelected entity={qs.entity} ids={sel} onDone={() => { setSel([]); qc.invalidateQueries() }} />}</div>
        </div>
        {meta.isLoading ? <Loading /> : fields.length > 0 && <GroupEditor fields={fields} g={qs.filter} onChange={(g) => setQs({ ...qs, filter: g })} />}
      </CardContent></Card>
      <Card>
        {res.isLoading ? <Loading /> : res.error ? <div className="p-4"><ErrorBox error={res.error} /></div> : (<>
          <div className="flex items-center justify-between border-b px-4 py-3 text-sm"><span data-testid="result-count"><b>{res.data!.total.toLocaleString()}</b> matching {ENTITIES.find(([k]) => k === qs.entity)?.[1].toLowerCase()}</span>
            {sel.length > 0 && <Badge variant="accent">{sel.length} selected</Badge>}</div>
          <Table data-testid="results"><THead><TR>{taggable && <TH className="w-8" />}{res.data!.columns.map((c) => <TH key={c.key}>{c.label}</TH>)}</TR></THead>
            <TBody>{res.data!.items.map((r) => (<TR key={r.id} className="cursor-pointer" onClick={() => nav(r.url)}>
              {taggable && <TD onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${r.label}`} checked={sel.includes(r.id)} onChange={(e) => setSel(e.target.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} /></TD>}
              {res.data!.columns.map((c, i) => <TD key={c.key} className={i === 0 ? 'font-medium' : ''}>{i === 0 && c.type === 'text' ? String(r[c.key] ?? r.label) : fmt(c.type, r[c.key])}</TD>)}</TR>))}
              {res.data!.items.length === 0 && <TR><TD colSpan={9} className="py-10 text-center text-muted-foreground">Nothing matches. Loosen a condition.</TD></TR>}</TBody></Table>
          <Pagination page={page} limit={15} total={res.data!.total} onPage={setPage} />
        </>)}
      </Card>
    </div>
  )
}

function SaveView({ qs, cleaned }: { qs: QS; cleaned: Group }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', '/views')
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><Save className="h-4 w-4" /> Save view</Button></DialogTrigger>
      <DialogContent><DialogTitle>Save view</DialogTitle><DialogDescription>Saves the filter, columns and sort.</DialogDescription>
        <div className="mt-4 grid gap-3"><Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Share with the team</label>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={!name} onClick={() => m.mutate({ name, entity: qs.entity, filter: cleaned, columns: qs.columns ?? [], sort_field: qs.sort_field, sort_dir: qs.sort_dir, visibility: shared ? 'shared' : 'private' }, { onSuccess: () => { setOpen(false); setName(''); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) })}>Save</Button></div></DialogContent>
    </Dialog>
  )
}

function SaveList({ qs, cleaned }: { qs: QS; cleaned: Group }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [kind, setKind] = useState('dynamic')
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', '/lists')
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="accent"><Camera className="h-4 w-4" /> Make list</Button></DialogTrigger>
      <DialogContent><DialogTitle>Create a list</DialogTitle><DialogDescription>Dynamic lists are recomputed every time. Static lists freeze today's members for a campaign.</DialogDescription>
        <div className="mt-4 grid gap-3"><Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Type"><Select className="w-full" aria-label="List type" value={kind} onChange={(e) => setKind(e.target.value)}><option value="dynamic">Dynamic (always current)</option><option value="static">Static snapshot (fixed members)</option></Select></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={!name} onClick={() => m.mutate({ name, entity: qs.entity, kind, filter: cleaned, visibility: 'shared' }, { onSuccess: () => { setOpen(false); setName(''); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) })}>Create list</Button></div></DialogContent>
    </Dialog>
  )
}

function TagSelected({ entity, ids, onDone }: { entity: string; ids: number[]; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [tag, setTag] = useState('')
  const [err, setErr] = useState('')
  const m = useSend<object, { updated: number }>('POST', '/tags/bulk')
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline" disabled={ids.length === 0}><Tag className="h-4 w-4" /> Tag selected</Button></DialogTrigger>
      <DialogContent><DialogTitle>Tag {ids.length} record{ids.length === 1 ? '' : 's'}</DialogTitle><DialogDescription>Tags are lowercase labels, up to 40 characters.</DialogDescription>
        <div className="mt-4 grid gap-3"><Input aria-label="Tag" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="e.g. q4-call-campaign" />
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={!tag} onClick={() => m.mutate({ entity, ids, add: [tag] }, { onSuccess: () => { setOpen(false); setTag(''); onDone() }, onError: (e) => setErr((e as Error).message) })}>Apply tag</Button></div></DialogContent>
    </Dialog>
  )
}

interface ViewT { id: number; name: string; entity: string; filter: object; columns: string[]; sort_field: string | null; sort_dir: string; visibility: string; owner: string; owner_user_id: number }
function Views({ onOpen }: { onOpen: (v: ViewT) => void }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { data, isLoading } = useApi<{ items: ViewT[] }>('/views')
  const del = useSend<number>('DELETE', (id) => `/views/${id}`)
  if (isLoading) return <Loading />
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="views">{data?.items.map((v) => (
      <Card key={v.id}><CardContent className="flex items-start justify-between gap-3 pt-5">
        <button className="cursor-pointer text-left" onClick={() => onOpen(v)}><div className="font-display text-lg font-semibold">{v.name}</div><div className="text-sm capitalize text-muted-foreground">{v.entity} view · {v.owner}</div></button>
        <div className="flex items-center gap-1"><Badge variant={v.visibility === 'shared' ? 'accent' : 'outline'}>{v.visibility}</Badge>
          {(v.owner_user_id === (user as { id: number }).id) && <Button size="icon" variant="ghost" aria-label={`Delete ${v.name}`} onClick={() => del.mutate(v.id, { onSuccess: () => qc.invalidateQueries() })}><Trash2 className="h-4 w-4" /></Button>}</div></CardContent></Card>))}</div>
  )
}

interface ListT { id: number; name: string; entity: string; kind: string; filter: object | null; description: string | null; member_count: number; owner: string; snapshot_at: string | null }
function ListsTab({ onOpen }: { onOpen: (l: ListT) => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data, isLoading } = useApi<{ items: ListT[] }>('/lists')
  const [sel, setSel] = useState<ListT | null>(null)
  const [page, setPage] = useState(1)
  const members = useApi<Result>(sel ? `/lists/${sel.id}/members` : '/lists/0/members', { page, limit: 10 }, { enabled: !!sel })
  const snap = useSend<{ id: number }>('POST', (b) => `/lists/${b.id}/snapshot`)
  if (isLoading) return <Loading />
  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-2" data-testid="lists">{data?.items.map((l) => (
        <button key={l.id} onClick={() => { setSel(l); setPage(1) }} className={`w-full cursor-pointer rounded-lg border p-3 text-left transition-colors ${sel?.id === l.id ? 'border-accent bg-accent/10' : 'bg-card hover:bg-secondary'}`}>
          <div className="flex items-center justify-between"><span className="font-medium">{l.name}</span><Badge variant={l.kind === 'dynamic' ? 'accent' : 'secondary'}>{l.kind}</Badge></div>
          <div className="text-xs text-muted-foreground capitalize">{l.entity} · {l.member_count} members · {l.owner}</div></button>))}</div>
      <Card>{!sel ? <CardContent className="py-16 text-center text-muted-foreground">Choose a list to see its members.</CardContent> : (<>
        <div className="flex items-center justify-between border-b px-4 py-3"><div><div className="font-display text-lg font-semibold">{sel.name}</div><div className="text-xs text-muted-foreground">{sel.description}{sel.snapshot_at ? ` · frozen ${fmtDate(sel.snapshot_at)}` : ' · recomputed on every view'}</div></div>
          <div className="flex gap-2">{sel.kind === 'dynamic' && <><Button size="sm" variant="outline" onClick={() => onOpen(sel)}>Edit filter</Button><Button size="sm" variant="accent" onClick={() => snap.mutate({ id: sel.id }, { onSuccess: () => qc.invalidateQueries() })}><Camera className="h-4 w-4" /> Snapshot</Button></>}</div></div>
        {members.isLoading ? <Loading /> : members.data && (<><Table><THead><TR>{members.data.columns.map((c) => <TH key={c.key}>{c.label}</TH>)}</TR></THead>
          <TBody>{members.data.items.map((r) => <TR key={r.id} className="cursor-pointer" onClick={() => nav(r.url)}>{members.data!.columns.map((c, i) => <TD key={c.key} className={i === 0 ? 'font-medium' : ''}>{fmt(c.type, r[c.key])}</TD>)}</TR>)}</TBody></Table>
          <Pagination page={page} limit={10} total={members.data.total} onPage={setPage} /></>)}</>)}</Card>
    </div>
  )
}

function Tags({ onPick }: { onPick: (entity: string, tag: string) => void }) {
  const [entity, setEntity] = useState('contact')
  const { data } = useApi<{ items: { tag: string; count: number }[] }>('/tags', { entity })
  return (
    <Card><CardContent className="pt-5"><div className="mb-4 flex gap-2"><Select aria-label="Tag entity" value={entity} onChange={(e) => setEntity(e.target.value)}>{ENTITIES.filter(([k]) => ['contact', 'company', 'property', 'listing', 'deal'].includes(k)).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></div>
      <div className="flex flex-wrap gap-2" data-testid="tags">{data?.items.map((t) => <button key={t.tag} onClick={() => onPick(entity, t.tag)} className="cursor-pointer"><Badge variant="accent" className="px-3 py-1 text-sm">{t.tag} <span className="opacity-60">{t.count}</span></Badge></button>)}
        {data?.items.length === 0 && <p className="text-sm text-muted-foreground">No tags yet.</p>}</div></CardContent></Card>
  )
}

interface DefT { id: number; entity: string; key: string; label: string; type: string; options: string[]; required: boolean; restricted: boolean; active: boolean }
function CustomFields() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { data } = useApi<{ items: DefT[]; types: string[] }>('/custom-fields', { include_retired: true })
  const add = useSend<object>('POST', '/custom-fields')
  const patch = useSend<{ id: number; active: boolean }>('PATCH', (b) => `/custom-fields/${b.id}`)
  const [f, setF] = useState({ entity: 'property', label: '', key: '', type: 'text', options: '', required: false })
  const [err, setErr] = useState('')
  const isAdmin = user?.role === 'admin'
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <Card><Table><THead><TR><TH>Entity</TH><TH>Label</TH><TH>Key</TH><TH>Type</TH><TH>Flags</TH>{isAdmin && <TH />}</TR></THead>
        <TBody>{data?.items.map((d) => (<TR key={d.id} className={d.active ? '' : 'opacity-50'}><TD className="capitalize">{d.entity}</TD><TD className="font-medium">{d.label}</TD><TD className="font-mono text-xs">{d.key}</TD><TD>{d.type.replace('_', ' ')}{d.options.length ? ` (${d.options.length})` : ''}</TD>
          <TD>{d.required && <Badge variant="warning">required</Badge>} {d.restricted && <Badge variant="destructive">restricted</Badge>} {!d.active && <Badge variant="outline">retired</Badge>}</TD>
          {isAdmin && <TD><Button size="sm" variant="ghost" onClick={() => patch.mutate({ id: d.id, active: !d.active }, { onSuccess: () => qc.invalidateQueries() })}>{d.active ? 'Retire' : 'Restore'}</Button></TD>}</TR>))}</TBody></Table></Card>
      <Card><CardContent className="pt-5">{isAdmin ? (<div className="grid gap-3"><h3 className="font-display text-lg font-semibold">Add a field</h3>
        <Field label="Entity"><Select className="w-full" aria-label="Field entity" value={f.entity} onChange={(e) => setF({ ...f, entity: e.target.value })}>{['property', 'contact', 'company', 'listing', 'deal', 'investor', 'fund'].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Label"><Input aria-label="Field label" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value, key: e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') })} /></Field>
        <Field label="Key"><Input aria-label="Field key" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} /></Field>
        <Field label="Type"><Select className="w-full" aria-label="Field type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{data?.types.map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</Select></Field>
        {f.type.includes('select') && <Field label="Options (comma separated)"><Input aria-label="Field options" value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} /></Field>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.required} onChange={(e) => setF({ ...f, required: e.target.checked })} /> Required</label>
        {err && <ErrorBox error={new Error(err)} />}
        <Button disabled={!f.label || !f.key} onClick={() => add.mutate({ entity: f.entity, key: f.key, label: f.label, type: f.type, options: f.options.split(',').map((x) => x.trim()).filter(Boolean), required: f.required }, { onSuccess: () => { setF({ ...f, label: '', key: '', options: '' }); setErr(''); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) })}>Add field</Button></div>)
        : <p className="text-sm text-muted-foreground">Only admins can define custom fields. Retired fields keep their data but disappear from screens.</p>}</CardContent></Card>
    </div>
  )
}
