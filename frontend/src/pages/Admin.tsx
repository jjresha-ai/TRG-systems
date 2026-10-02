import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound, Plus, ShieldCheck, UserX } from 'lucide-react'
import { api } from '@/api/client'
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
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading, Pagination } from '@/components/common'
import { fmtDate } from '@/lib/utils'

interface AdminUser { id: number; email: string; name: string; role: string; title: string | null; team: string | null; active: boolean; owned: Record<string, number>; open_tasks: number; owns_records: number }
interface Token { id: number; name: string; prefix: string; scopes: string[]; owner: string; created_at: string; expires_at: string | null; last_used_at: string | null; active: boolean; token?: string; note?: string }
interface Ev { id: number; timestamp: string; actor: string; action: string; entity_type: string; entity_id: number | null; changes: Record<string, unknown> }

export default function Admin() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  return (
    <div className="rise">
      <PageHeader title="Admin & Audit" subtitle="Who can do what, every change that was made, and how the system runs." />
      <Tabs defaultValue={isAdmin ? 'users' : 'tokens'}>
        <TabsList>{isAdmin && <TabsTrigger value="users">Users & roles</TabsTrigger>}<TabsTrigger value="tokens">API tokens</TabsTrigger>{isAdmin && <TabsTrigger value="audit">Audit trail</TabsTrigger>}{isAdmin && <TabsTrigger value="jobs">Background jobs</TabsTrigger>}<TabsTrigger value="settings">Settings</TabsTrigger></TabsList>
        {isAdmin && <TabsContent value="users"><Users /></TabsContent>}
        <TabsContent value="tokens"><Tokens /></TabsContent>
        {isAdmin && <TabsContent value="audit"><Audit /></TabsContent>}
        {isAdmin && <TabsContent value="jobs"><Jobs /></TabsContent>}
        <TabsContent value="settings"><Settings /></TabsContent>
      </Tabs>
    </div>
  )
}

function Users() {
  const qc = useQueryClient()
  const { data, isLoading } = useApi<{ items: AdminUser[]; roles: string[]; role_actions: Record<string, string[]> }>('/admin/users')
  const [err, setErr] = useState('')
  const setRole = useSend<{ id: number; role: string }>('PATCH', (b) => `/admin/users/${b.id}`)
  const reactivate = useSend<number>('POST', (id) => `/admin/users/${id}/reactivate`)
  if (isLoading || !data) return <Loading />
  const refresh = () => qc.invalidateQueries()
  return (
    <div className="space-y-4">
      {err && <ErrorBox error={new Error(err)} />}
      <Card><div className="flex items-center justify-between border-b p-4"><div className="text-sm text-muted-foreground">{data.items.filter((u) => u.active).length} active users</div><AddUser onDone={refresh} /></div>
        <Table data-testid="users"><THead><TR><TH>User</TH><TH>Role</TH><TH>Team</TH><TH className="text-right">Owns</TH><TH>Status</TH><TH /></TR></THead>
          <TBody>{data.items.map((u) => (<TR key={u.id} className={u.active ? '' : 'opacity-60'}><TD><div className="font-medium">{u.name}</div><div className="text-xs text-muted-foreground">{u.email}</div></TD>
            <TD><Select aria-label={`Role for ${u.name}`} value={u.role} className="h-8" disabled={!u.active} onChange={(e) => { setErr(''); setRole.mutate({ id: u.id, role: e.target.value }, { onSuccess: refresh, onError: (x) => setErr((x as Error).message) }) }}>{data.roles.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</Select></TD>
            <TD>{u.team}</TD><TD className="text-right tabular-nums">{u.owns_records}</TD><TD><Badge variant={u.active ? 'success' : 'secondary'}>{u.active ? 'Active' : 'Inactive'}</Badge></TD>
            <TD className="text-right"><div className="flex justify-end gap-1">{u.active ? <><ResetPassword u={u} /><Deactivate u={u} users={data.items} onDone={refresh} /></> : <Button size="sm" variant="outline" onClick={() => reactivate.mutate(u.id, { onSuccess: refresh })}>Reactivate</Button>}</div></TD></TR>))}</TBody></Table></Card>
      <Card><CardHeader><CardTitle>What each role can do</CardTitle></CardHeader><CardContent><div className="grid gap-3 md:grid-cols-5">{data.roles.map((r) => (
        <div key={r}><div className="mb-1 text-sm font-semibold capitalize">{r.replace('_', ' ')}</div><div className="flex flex-wrap gap-1">{data.role_actions[r].map((a) => <Badge key={a} variant={a === 'admin' ? 'destructive' : 'secondary'}>{a}</Badge>)}</div></div>))}</div>
        <p className="mt-3 text-xs text-muted-foreground">Enforced by the backend on every request. Commission and accreditation fields are additionally hidden from assistants and read-only users.</p></CardContent></Card>
    </div>
  )
}

function AddUser({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: '', email: '', role: 'broker', team: 'Resha Group', password: '' })
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', '/admin/users')
  return (
    <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="sm" variant="accent"><Plus className="h-4 w-4" /> Add user</Button></DialogTrigger>
      <DialogContent><DialogTitle>Add a user</DialogTitle><DialogDescription>Passwords are at least 8 characters and stored as salted PBKDF2 hashes.</DialogDescription>
        <div className="mt-4 grid gap-3"><Field label="Name"><Input aria-label="User name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field><Field label="Email"><Input aria-label="User email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Role"><Select className="w-full" aria-label="User role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{['admin', 'manager', 'broker', 'assistant', 'read_only'].map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}</Select></Field>
            <Field label="Team"><Input value={f.team} onChange={(e) => setF({ ...f, team: e.target.value })} /></Field></div>
          <Field label="Initial password"><Input aria-label="User password" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button onClick={() => m.mutate(f, { onSuccess: () => { setOpen(false); onDone() }, onError: (e) => setErr((e as Error).message) })}>Create user</Button></div></DialogContent></Dialog>
  )
}

function ResetPassword({ u }: { u: AdminUser }) {
  const [open, setOpen] = useState(false)
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', `/admin/users/${u.id}/reset-password`)
  return (
    <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="icon" variant="ghost" aria-label={`Reset password for ${u.name}`}><KeyRound className="h-4 w-4" /></Button></DialogTrigger>
      <DialogContent><DialogTitle>Reset password for {u.name}</DialogTitle><div className="mt-4 grid gap-3"><Input aria-label="New password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />{err && <ErrorBox error={new Error(err)} />}
        <Button onClick={() => m.mutate({ password: pw }, { onSuccess: () => { setOpen(false); setPw('') }, onError: (e) => setErr((e as Error).message) })}>Set password</Button></div></DialogContent></Dialog>
  )
}

function Deactivate({ u, users, onDone }: { u: AdminUser; users: AdminUser[]; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [to, setTo] = useState('')
  const [err, setErr] = useState('')
  const m = useSend<{ reassign_to?: number }>('POST', `/admin/users/${u.id}/deactivate`)
  return (
    <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button size="icon" variant="ghost" aria-label={`Deactivate ${u.name}`}><UserX className="h-4 w-4" /></Button></DialogTrigger>
      <DialogContent><DialogTitle>Deactivate {u.name}</DialogTitle><DialogDescription>Deactivating revokes sign-in and API tokens. Records and open tasks must be reassigned first.</DialogDescription>
        <div className="mt-4 grid gap-3">{u.owns_records > 0 && <div className="rounded-md border bg-muted/50 p-3 text-sm">Owns {u.owns_records} items: {Object.entries(u.owned).filter(([, v]) => v).map(([k, v]) => `${v} ${k}`).join(', ')}{u.open_tasks ? `, ${u.open_tasks} open tasks` : ''}.</div>}
          <Field label="Reassign everything to"><Select className="w-full" aria-label="Reassign to" value={to} onChange={(e) => setTo(e.target.value)}><option value="">Choose a user…</option>{users.filter((x) => x.active && x.id !== u.id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button variant="destructive" onClick={() => m.mutate({ reassign_to: to ? Number(to) : undefined }, { onSuccess: () => { setOpen(false); onDone() }, onError: (e) => setErr((e as Error).message) })}>Reassign and deactivate</Button></div></DialogContent></Dialog>
  )
}

function Tokens() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { data } = useApi<{ items: Token[] }>('/tokens')
  const scopes: Record<string, string[]> = { admin: ['view', 'create', 'edit', 'delete', 'export', 'import'], manager: ['view', 'create', 'edit', 'delete', 'export', 'import'], broker: ['view', 'create', 'edit', 'export', 'import'], assistant: ['view', 'create', 'edit'], read_only: ['view'] }
  const [name, setName] = useState('')
  const [sel, setSel] = useState<string[]>(['view'])
  const [made, setMade] = useState<Token | null>(null)
  const [err, setErr] = useState('')
  const create = useSend<object, Token>('POST', '/tokens')
  const revoke = useSend<number>('DELETE', (id) => `/tokens/${id}`)
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <Card><Table data-testid="tokens"><THead><TR><TH>Name</TH><TH>Scopes</TH><TH>Last used</TH><TH>Expires</TH><TH /></TR></THead>
        <TBody>{data?.items.map((t) => (<TR key={t.id} className={t.active ? '' : 'opacity-50'}><TD><div className="font-medium">{t.name}</div><div className="font-mono text-xs text-muted-foreground">trg_{t.prefix}_…</div></TD><TD><div className="flex flex-wrap gap-1">{t.scopes.map((s) => <Badge key={s} variant="secondary">{s}</Badge>)}</div></TD>
          <TD className="text-muted-foreground">{t.last_used_at ? fmtDate(t.last_used_at) : 'Never'}</TD><TD>{t.active ? fmtDate(t.expires_at) : <Badge variant="outline">revoked</Badge>}</TD>
          <TD>{t.active && <Button size="sm" variant="ghost" onClick={() => revoke.mutate(t.id, { onSuccess: () => qc.invalidateQueries() })}>Revoke</Button>}</TD></TR>))}
          {data?.items.length === 0 && <TR><TD colSpan={5} className="py-8 text-center text-muted-foreground">No tokens yet.</TD></TR>}</TBody></Table></Card>
      <Card><CardHeader><CardTitle>New API token</CardTitle></CardHeader><CardContent className="space-y-3">
        <Input aria-label="Token name" placeholder="e.g. Zapier lead form" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="flex flex-wrap gap-3 text-sm">{(scopes[user?.role ?? 'read_only']).map((s) => <label key={s} className="flex items-center gap-1"><input type="checkbox" checked={sel.includes(s)} onChange={(e) => setSel(e.target.checked ? [...sel, s] : sel.filter((x) => x !== s))} />{s}</label>)}</div>
        {err && <ErrorBox error={new Error(err)} />}
        <Button disabled={!name || sel.length === 0} onClick={() => { setErr(''); create.mutate({ name, scopes: sel }, { onSuccess: (t) => { setMade(t); setName(''); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) }) }}><Plus className="h-4 w-4" /> Create token</Button>
        {made?.token && <div role="status" className="rounded-md border border-accent bg-accent/10 p-3 text-sm"><div className="mb-1 font-semibold">Copy it now: shown only once</div><div className="flex items-center gap-2"><code className="break-all text-xs">{made.token}</code><button aria-label="Copy token" className="cursor-pointer" onClick={() => navigator.clipboard?.writeText(made.token!)}><Copy className="h-4 w-4" /></button></div></div>}
        <p className="text-xs text-muted-foreground">A token can never do more than its user's role allows. Every request made with a token is written to the audit trail.</p></CardContent></Card>
    </div>
  )
}

const summarize = (c: Record<string, unknown>) => Object.entries(c).slice(0, 3).map(([k, v]) => (Array.isArray(v) ? `${k}: ${String(v[0] ?? '∅')} → ${String(v[1] ?? '∅')}` : `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)).join(' · ')

function Audit() {
  const facets = useApi<{ actions: string[]; entity_types: string[] }>('/audit/facets')
  const [f, setF] = useState({ actor: '', entity_type: '', action: '', entity_id: '' })
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<Ev | null>(null)
  const { data, isLoading } = useApi<Page<Ev>>('/audit', { ...f, page, limit: 20 })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-4">
          <Input aria-label="Filter by actor" className="max-w-[12rem]" placeholder="Actor…" value={f.actor} onChange={set('actor')} />
          <Select aria-label="Entity type" value={f.entity_type} onChange={set('entity_type')}><option value="">Any record type</option>{facets.data?.entity_types.map((x) => <option key={x}>{x}</option>)}</Select>
          <Select aria-label="Action" value={f.action} onChange={set('action')}><option value="">Any action</option>{facets.data?.actions.map((x) => <option key={x}>{x}</option>)}</Select>
          <Input aria-label="Record id" type="number" className="w-28" placeholder="Record #" value={f.entity_id} onChange={set('entity_id')} />
        </div>
        {isLoading || !data ? <Loading /> : (<><Table data-testid="audit"><THead><TR><TH>When</TH><TH>Who</TH><TH>Action</TH><TH>Record</TH><TH>Change</TH></TR></THead>
          <TBody>{data.items.map((e) => (<TR key={e.id} className="cursor-pointer" onClick={() => setOpen(e)}><TD className="whitespace-nowrap text-muted-foreground">{new Date(e.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</TD>
            <TD className={e.actor.startsWith('rule:') ? 'font-medium text-[#7a5614]' : ''}>{e.actor}</TD><TD><Badge variant={e.action === 'create' ? 'success' : e.action.includes('fail') || e.action.includes('lock') ? 'destructive' : e.action === 'update' ? 'accent' : 'secondary'}>{e.action}</Badge></TD>
            <TD>{e.entity_type}{e.entity_id ? ` #${e.entity_id}` : ''}</TD><TD className="max-w-md truncate text-xs text-muted-foreground">{summarize(e.changes)}</TD></TR>))}</TBody></Table>
          <Pagination page={page} limit={20} total={data.total} onPage={setPage} /></>)}
      </Card>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}><DialogContent className="max-w-xl">{open && (<><DialogTitle>{open.action} · {open.entity_type}{open.entity_id ? ` #${open.entity_id}` : ''}</DialogTitle><DialogDescription>{open.actor} · {new Date(open.timestamp).toLocaleString()}</DialogDescription>
        <table className="mt-4 w-full text-sm"><tbody>{Object.entries(open.changes).map(([k, v]) => <tr key={k} className="border-b"><td className="py-1.5 pr-3 font-medium">{k}</td><td className="py-1.5 text-muted-foreground">{Array.isArray(v) ? `${String(v[0] ?? '∅')} → ${String(v[1] ?? '∅')}` : JSON.stringify(v)}</td></tr>)}
          {Object.keys(open.changes).length === 0 && <tr><td className="py-2 text-muted-foreground">No field changes recorded.</td></tr>}</tbody></table></>)}</DialogContent></Dialog>
    </div>
  )
}

function Jobs() {
  const qc = useQueryClient()
  const { data } = useApi<{ name: string; description: string; last_run: { status: string; finished_at: string; summary: Record<string, unknown> } | null }[]>('/jobs')
  const [msg, setMsg] = useState('')
  return (
    <Card><CardContent className="pt-5"><ul className="divide-y" data-testid="jobs">{data?.map((j) => (
      <li key={j.name} className="flex items-center justify-between gap-4 py-3"><div><div className="font-mono text-sm font-semibold">{j.name}</div><div className="text-sm text-muted-foreground">{j.description}</div>
        {j.last_run && <div className="text-xs text-muted-foreground">Last run {fmtDate(j.last_run.finished_at)}: {j.last_run.status} {JSON.stringify(j.last_run.summary)}</div>}</div>
        <Button size="sm" variant="outline" onClick={() => api(`/jobs/${j.name}/run`, { method: 'POST' }).then(() => { setMsg(`${j.name} ran`); qc.invalidateQueries() })}>Run now</Button></li>))}</ul>
      {msg && <p role="status" className="mt-3 text-sm text-success">{msg}</p>}
      <p className="mt-3 text-xs text-muted-foreground">A scheduler thread runs these hourly in development. A separate worker is a later hosting decision.</p></CardContent></Card>
  )
}

function Settings() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const s = useApi<{ visibility_mode: string }>('/settings')
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const vis = useSend<{ mode: string }>('PUT', '/settings/visibility')
  const pw = useSend<object>('POST', '/auth/change-password')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-accent" /> Who can see whose relationships</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        {[['firm_open', 'Firm-open', 'Everyone sees every owner, entity and property. Prevents two brokers from calling the same owner. (Default; needs Jim’s confirmation.)'], ['team_scoped', 'Team-scoped', 'Brokers see their own team’s records. Managers and admins see everything.']].map(([k, l, d]) => (
          <label key={k} className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${s.data?.visibility_mode === k ? 'border-accent bg-accent/10' : ''}`}><input type="radio" name="vis" aria-label={l} checked={s.data?.visibility_mode === k} disabled={user?.role !== 'admin'}
            onChange={() => vis.mutate({ mode: k }, { onSuccess: () => qc.invalidateQueries() })} /><span><b>{l}</b><br /><span className="text-muted-foreground">{d}</span></span></label>))}
        <p className="text-xs text-muted-foreground">Records can also be marked confidential, which makes them visible only to their owner, managers and admins, in either mode.{user?.role !== 'admin' && ' Only admins can change this setting.'}</p></CardContent></Card>
      <Card><CardHeader><CardTitle>Change my password</CardTitle></CardHeader><CardContent className="space-y-3">
        <Input aria-label="Current password" type="password" placeholder="Current password" value={cur} onChange={(e) => setCur(e.target.value)} /><Input aria-label="New password (8+ characters)" type="password" placeholder="New password (8+ characters)" value={next} onChange={(e) => setNext(e.target.value)} />
        {err && <ErrorBox error={new Error(err)} />}{msg && <p role="status" className="text-sm text-success">{msg}</p>}
        <Button disabled={!cur || next.length < 8} onClick={() => { setErr(''); setMsg(''); pw.mutate({ current_password: cur, new_password: next }, { onSuccess: () => { setMsg('Password changed.'); setCur(''); setNext('') }, onError: (e) => setErr((e as Error).message) }) }}>Change password</Button></CardContent></Card>
    </div>
  )
}
