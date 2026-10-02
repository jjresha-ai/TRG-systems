import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, RotateCcw, Upload } from 'lucide-react'
import { getToken } from '@/api/client'
import { useApi, useSend, type Page } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { ErrorBox, Field, Loading, Pagination, Stat } from '@/components/common'
import { downloadFile } from '@/lib/download'
import { fmtDate } from '@/lib/utils'

interface Job {
  id: number; file_name: string; entity: string; mode: string; source_name: string; mapping: Record<string, string>; headers: string[]; status: string; total_rows: number
  counts: Record<string, number>; summary: { records_created?: Record<string, number>; rollback?: { removed: Record<string, number>; kept: { entity: string; id: number }[] } }; created_by: string | null
  created_at: string; finished_at: string | null; processed: number | null
}
interface Target { field: string; label: string; required: boolean }
interface RowT { row_no: number; action: string; message: string | null; raw: Record<string, string> }

const ENT: [string, string, string][] = [['contact', 'Contacts', 'People: owners, buyers, investors'], ['company', 'Companies', 'LLCs, trusts, funds, lenders'], ['property', 'Properties', 'Assets with APN, size, debt'], ['owner_properties', 'Owners + entities + properties', 'One file builds the whole owner graph']]
const ACTION_VARIANT: Record<string, 'success' | 'accent' | 'secondary' | 'warning' | 'destructive'> = { create: 'success', update: 'accent', skip: 'secondary', duplicate: 'warning', error: 'destructive' }

export default function DataPage() {
  const [tab, setTab] = useState('import')
  const [openJob, setOpenJob] = useState<number | null>(null)
  return (
    <div className="rise">
      <PageHeader title="Import / Export" subtitle="Bring in spreadsheets and vendor lists with a preview, duplicate checks and rollback. Take everything out with relationship history." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList><TabsTrigger value="import">Import</TabsTrigger><TabsTrigger value="history">History</TabsTrigger><TabsTrigger value="export">Export</TabsTrigger></TabsList>
        <TabsContent value="import"><Wizard initialJob={openJob} onClose={() => setOpenJob(null)} /></TabsContent>
        <TabsContent value="history"><History onOpen={(id) => { setOpenJob(id); setTab('import') }} /></TabsContent>
        <TabsContent value="export"><ExportTab /></TabsContent>
      </Tabs>
    </div>
  )
}

function Wizard({ initialJob, onClose }: { initialJob: number | null; onClose: () => void }) {
  const [jobId, setJobId] = useState<number | null>(initialJob)
  useEffect(() => { if (initialJob) setJobId(initialJob) }, [initialJob])
  if (jobId) return <JobView id={jobId} onDone={() => { setJobId(null); onClose() }} />
  return <Upload_ onCreated={setJobId} />
}

function Upload_({ onCreated }: { onCreated: (id: number) => void }) {
  const [entity, setEntity] = useState('owner_properties')
  const [mode, setMode] = useState('create_or_update')
  const [source, setSource] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const tpl = useApi<{ csv_header: string; fields: Target[] }>('/imports/templates', { entity })
  const submit = async () => {
    const f = file.current?.files?.[0]
    if (!f) return setErr('Choose a .csv or .xlsx file')
    setBusy(true); setErr('')
    const fd = new FormData()
    fd.append('file', f); fd.append('entity', entity); fd.append('mode', mode); fd.append('source_name', source)
    const res = await fetch('/api/imports', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${getToken()}` } })
    setBusy(false)
    const j = await res.json().catch(() => ({}))
    if (!res.ok) return setErr(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail))
    onCreated(j.id)
  }
  const template = () => {
    const blob = new Blob([tpl.data!.csv_header + '\n'], { type: 'text/csv' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${entity}-template.csv`; a.click()
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <Card><CardHeader><CardTitle>1. What are you importing?</CardTitle></CardHeader><CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">{ENT.map(([k, l, d]) => (
          <button key={k} onClick={() => setEntity(k)} aria-pressed={entity === k} className={`cursor-pointer rounded-lg border p-3 text-left transition-colors ${entity === k ? 'border-accent bg-accent/10' : 'bg-card hover:bg-secondary'}`}><div className="font-medium">{l}</div><div className="text-xs text-muted-foreground">{d}</div></button>))}</div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Source name (kept as provenance)"><Input aria-label="Source name" value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. CoStar export Oct 2026" /></Field>
          <Field label="If a record already exists"><Select className="w-full" aria-label="Import mode" value={mode} onChange={(e) => setMode(e.target.value)}><option value="create">Skip it (create new only)</option><option value="create_or_update">Update it, create the rest</option><option value="update">Update only, create nothing</option></Select></Field>
        </div>
        <Field label="File (.csv or .xlsx, up to 5 MB)"><input ref={file} type="file" aria-label="Import file" accept=".csv,.xlsx,.txt" className="text-sm" /></Field>
        {err && <ErrorBox error={new Error(err)} />}
        <div className="flex items-center gap-3"><Button variant="accent" disabled={busy || !source.trim()} onClick={submit}><Upload className="h-4 w-4" /> Preview import</Button>
          <button className="cursor-pointer text-sm text-primary hover:underline" onClick={template} disabled={!tpl.data}>Download CSV template</button></div>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>What happens next</CardTitle></CardHeader><CardContent className="space-y-3 text-sm text-muted-foreground">
        <p><b className="text-foreground">Nothing is written yet.</b> You get a dry-run preview: what would be created, updated, skipped, flagged as duplicates or rejected, row by row.</p>
        <p>Duplicates are caught by email, phone, APN, address and normalized entity names, so “Acme, L.L.C.” matches “Acme LLC”.</p>
        <p>Every record keeps its source and import job, so a refreshed feed updates instead of duplicating, and a bad import can be rolled back.</p>
        <p className="text-xs">Fields for this import: {tpl.data?.fields.map((f) => f.label).join(', ')}</p></CardContent></Card>
    </div>
  )
}

function JobView({ id, onDone }: { id: number; onDone: () => void }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const job = useApi<Job>(`/imports/${id}`, undefined, { refetchInterval: 1000 })
  const tpl = useApi<{ fields: Target[] }>('/imports/templates', { entity: job.data?.entity }, { enabled: !!job.data })
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const rows = useApi<Page<RowT> & { items: RowT[] }>(`/imports/${id}/rows`, { action, page, limit: 12 })
  const [mapping, setMapping] = useState<Record<string, string> | null>(null)
  const [err, setErr] = useState('')
  const remap = useSend<{ mapping?: Record<string, string> }>('PUT', `/imports/${id}`)
  const commit = useSend<null>('POST', `/imports/${id}/commit`)
  const rollback = useSend<null, { removed: Record<string, number>; kept: unknown[] }>('POST', `/imports/${id}/rollback`)
  useEffect(() => { if (job.data && mapping === null) setMapping(job.data.mapping) }, [job.data, mapping])
  if (job.isLoading || !job.data || !mapping) return <Loading />
  const j = job.data
  const previewing = j.status === 'previewed'
  const canRollback = j.status === 'completed' && user && ['admin', 'manager'].includes(user.role)
  const refresh = () => qc.invalidateQueries()
  const created = j.summary.records_created
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><div><div className="font-display text-xl font-semibold">{j.file_name}</div><div className="text-sm text-muted-foreground">{j.entity.replace('_', ' ')} · source “{j.source_name}” · mode {j.mode.replace(/_/g, ' ')} · {j.total_rows} rows</div></div>
        <div className="flex items-center gap-2"><Badge variant={j.status === 'completed' ? 'success' : j.status === 'running' ? 'accent' : j.status === 'rolled_back' ? 'destructive' : 'secondary'} className="capitalize">{j.status.replace('_', ' ')}</Badge><Button variant="ghost" size="sm" onClick={onDone}>{previewing ? 'Cancel' : 'Close'}</Button></div></div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5" data-testid="counts">
        {['create', 'update', 'duplicate', 'skip', 'error'].map((k) => <Stat key={k} label={k === 'create' ? 'Will create' : k === 'update' ? 'Will update' : k === 'duplicate' ? 'Duplicates' : k === 'skip' ? 'Skipped' : 'Errors'} value={j.counts[k] ?? 0} className={k === 'error' && (j.counts.error ?? 0) > 0 ? 'border-destructive/50' : ''} />)}
      </div>
      {j.status === 'running' && <Card><CardContent className="flex items-center gap-3 pt-5 text-sm"><div className="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full animate-pulse bg-accent" style={{ width: '60%' }} /></div>Importing in the background… {j.processed ?? 0} of {j.total_rows} rows</CardContent></Card>}
      {j.status === 'completed' && created && <div role="status" className="flex items-center gap-2 rounded-md border border-success/30 bg-success/10 p-3 text-sm text-success"><CheckCircle2 className="h-4 w-4" /> Import complete: {created.contacts} contacts, {created.companies} companies, {created.properties} properties, {created.ownerships} ownership records created.</div>}
      {j.status === 'rolled_back' && j.summary.rollback && <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">Rolled back: removed {j.summary.rollback.removed.contacts} contacts, {j.summary.rollback.removed.companies} companies, {j.summary.rollback.removed.properties} properties. {j.summary.rollback.kept.length > 0 && `${j.summary.rollback.kept.length} were kept because they were changed or used after the import.`}</div>}
      {err && <ErrorBox error={new Error(err)} />}
      {previewing && tpl.data && (
        <Card><CardHeader><CardTitle>2. Map your columns</CardTitle></CardHeader><CardContent>
          <div className="grid gap-x-6 gap-y-2 md:grid-cols-2" data-testid="mapping">{tpl.data.fields.map((t) => (
            <label key={t.field} className="flex items-center justify-between gap-2 text-sm"><span>{t.label}{t.required && <span className="text-destructive"> *</span>}</span>
              <Select aria-label={`Map ${t.label}`} className="w-48" value={mapping[t.field] ?? ''} onChange={(e) => { const m = { ...mapping }; if (e.target.value) m[t.field] = e.target.value; else delete m[t.field]; setMapping(m) }}><option value="">— not mapped —</option>{j.headers.map((h) => <option key={h}>{h}</option>)}</Select></label>))}</div>
          <Button className="mt-4" variant="outline" size="sm" onClick={() => { setErr(''); remap.mutate({ mapping }, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) }) }}><RotateCcw className="h-4 w-4" /> Re-run preview with this mapping</Button>
        </CardContent></Card>)}
      <Card>
        <div className="flex flex-wrap items-center gap-1 border-b p-3" role="tablist">{['', 'create', 'update', 'duplicate', 'skip', 'error'].map((a) => (
          <button key={a} role="tab" aria-selected={action === a} onClick={() => { setAction(a); setPage(1) }} className={`cursor-pointer rounded-full px-3 py-1 text-xs font-semibold capitalize ${action === a ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-secondary'}`}>{a || 'All rows'}</button>))}
          <div className="ml-auto flex gap-2"><Button size="sm" variant="outline" onClick={() => downloadFile(`/imports/${id}/errors.csv`, {}, `import-${id}-errors.csv`).catch((e) => setErr(e.message))}><Download className="h-4 w-4" /> Row error report</Button></div></div>
        {rows.data ? (<><Table data-testid="rows"><THead><TR><TH>Row</TH><TH>Result</TH><TH>Detail</TH><TH>Data</TH></TR></THead>
          <TBody>{rows.data.items.map((r) => (<TR key={r.row_no}><TD className="tabular-nums">{r.row_no}</TD><TD><Badge variant={ACTION_VARIANT[r.action]} className="capitalize">{r.action}</Badge></TD><TD className="max-w-md text-sm">{r.message}</TD>
            <TD className="max-w-xs truncate text-xs text-muted-foreground">{Object.values(r.raw).slice(0, 4).join(' · ')}</TD></TR>))}</TBody></Table>
          <Pagination page={page} limit={12} total={rows.data.total} onPage={setPage} /></>) : <Loading />}
      </Card>
      <div className="flex flex-wrap items-center gap-3">
        {previewing && <Button variant="accent" size="lg" disabled={commit.isPending || (j.counts.create ?? 0) + (j.counts.update ?? 0) === 0} onClick={() => { setErr(''); commit.mutate(null, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) }) }}><FileSpreadsheet className="h-4 w-4" /> Import {(j.counts.create ?? 0) + (j.counts.update ?? 0)} rows</Button>}
        {previewing && (j.counts.error ?? 0) > 0 && <span className="flex items-center gap-1 text-sm text-muted-foreground"><AlertTriangle className="h-4 w-4 text-warning" /> {j.counts.error} rows with errors will be skipped.</span>}
        {canRollback && <Button variant="destructive" onClick={() => { setErr(''); rollback.mutate(null, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) }) }}><RotateCcw className="h-4 w-4" /> Roll back this import</Button>}
        {j.status === 'completed' && <Link to={j.entity === 'contact' ? '/contacts' : j.entity === 'company' ? '/companies' : '/properties'} className="text-sm text-primary hover:underline">View imported records →</Link>}
      </div>
    </div>
  )
}

function History({ onOpen }: { onOpen: (id: number) => void }) {
  const { data, isLoading } = useApi<{ items: Job[] }>('/imports')
  if (isLoading) return <Loading />
  return (
    <Card><Table data-testid="history"><THead><TR><TH>File</TH><TH>Source</TH><TH>Entity</TH><TH>Status</TH><TH className="text-right">Rows</TH><TH className="text-right">Created</TH><TH className="text-right">Errors</TH><TH>By</TH><TH>When</TH></TR></THead>
      <TBody>{data?.items.map((j) => (<TR key={j.id} className="cursor-pointer" onClick={() => onOpen(j.id)}><TD className="font-medium">{j.file_name}</TD><TD>{j.source_name}</TD><TD className="capitalize">{j.entity.replace('_', ' ')}</TD>
        <TD><Badge variant={j.status === 'completed' ? 'success' : j.status === 'rolled_back' ? 'destructive' : 'secondary'} className="capitalize">{j.status.replace('_', ' ')}</Badge></TD><TD className="text-right tabular-nums">{j.total_rows}</TD><TD className="text-right tabular-nums">{j.counts.create ?? 0}</TD>
        <TD className="text-right tabular-nums">{j.counts.error ?? 0}</TD><TD>{j.created_by}</TD><TD className="text-muted-foreground">{fmtDate(j.created_at)}</TD></TR>))}</TBody></Table></Card>
  )
}

function ExportTab() {
  const { user } = useAuth()
  const [entity, setEntity] = useState('property')
  const [fmt, setFmt] = useState('csv')
  const [view, setView] = useState('')
  const [list, setList] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const views = useApi<{ items: { id: number; name: string }[] }>('/views', { entity })
  const lists = useApi<{ items: { id: number; name: string }[] }>('/lists', { entity })
  const can = !!user && ['admin', 'manager', 'broker'].includes(user.role)
  const run = (fn: () => Promise<void>) => { setErr(''); setMsg(''); fn().then(() => setMsg('Download started. This export was recorded in the audit trail.')).catch((e) => setErr(e.message)) }
  if (!can) return <Card><CardContent className="py-12 text-center text-muted-foreground">Your role does not have export access.</CardContent></Card>
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Export a table</CardTitle></CardHeader><CardContent className="space-y-3">
        <Field label="Records"><Select className="w-full" aria-label="Export entity" value={entity} onChange={(e) => { setEntity(e.target.value); setView(''); setList('') }}>{['property', 'contact', 'company', 'listing', 'deal', 'lead'].map((e) => <option key={e} value={e}>{e}</option>)}</Select></Field>
        <Field label="Limit to a saved view"><Select className="w-full" aria-label="Export view" value={view} onChange={(e) => { setView(e.target.value); setList('') }}><option value="">Everything I can see</option>{views.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select></Field>
        <Field label="…or a list"><Select className="w-full" aria-label="Export list" value={list} onChange={(e) => { setList(e.target.value); setView('') }}><option value="">No list</option>{lists.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select></Field>
        <Field label="Format"><Select className="w-full" aria-label="Export format" value={fmt} onChange={(e) => setFmt(e.target.value)}><option value="csv">CSV</option><option value="xlsx">Excel (.xlsx)</option></Select></Field>
        <Button onClick={() => run(() => downloadFile(`/export/${entity}`, { format: fmt, view_id: view || undefined, list_id: list || undefined }, `${entity}.${fmt}`))}><Download className="h-4 w-4" /> Download</Button>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Full export with relationship history</CardTitle></CardHeader><CardContent className="space-y-3 text-sm text-muted-foreground">
        <p>One Excel workbook with contacts, companies, properties, listings, deals and leads, plus ownership history, contact-company roles, every activity, note metadata and buyer interest. This is what lets the firm keep its relationship history if it ever changes systems.</p>
        <p>Private notes and note bodies are never included. Exports are rate-limited and audited.</p>
        <Button variant="accent" onClick={() => run(() => downloadFile('/export-full', {}, 'trg-full-export.xlsx'))}><Download className="h-4 w-4" /> Download full export</Button>
      </CardContent></Card>
      {msg && <div role="status" className="rounded-md border border-success/30 bg-success/10 p-3 text-sm text-success lg:col-span-2">{msg}</div>}
      {err && <div className="lg:col-span-2"><ErrorBox error={new Error(err)} /></div>}
    </div>
  )
}
