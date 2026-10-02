import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, Play, Plus, ScrollText, Trash2, Zap } from 'lucide-react'
import { api } from '@/api/client'
import { useApi, useSend, useUsers } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading } from '@/components/common'
import { GroupEditor, clean, type FieldMeta, type Group } from '@/components/FilterBuilder'
import { fmtDate } from '@/lib/utils'

interface Rule {
  id: number; name: string; description: string | null; owner: string | null; enabled: boolean; entity: string; trigger_type: string; trigger_config: Record<string, unknown>; conditions: Group | null
  actions: { type: string; params: Record<string, unknown> }[]; actions_logged: number; last_run: { at: string; status: string; matched: number; actions_taken: number } | null
}
interface Meta { entities: string[]; triggers: string[]; actions: string[]; date_fields: Record<string, string[]>; set_field: Record<string, Record<string, string[]>> }

const trig = (r: Pick<Rule, 'trigger_type' | 'trigger_config' | 'entity'>) => {
  const c = r.trigger_config
  switch (r.trigger_type) {
    case 'record_created': return `When a ${r.entity} is created`
    case 'field_changed': return `When a ${r.entity}'s ${String(c.field).replace(/_/g, ' ')} changes${c.to ? ` to “${String(c.to)}”` : ''}`
    case 'stage_changed': return `When a deal moves to ${c.to_stage ? String(c.to_stage).replace(/_/g, ' ') : 'a new stage'}`
    case 'date_reached': return `${Math.abs(Number(c.offset_days ?? 0))} days ${Number(c.offset_days ?? 0) < 0 ? 'before' : 'after'} a ${r.entity}'s ${String(c.date_field).replace(/_/g, ' ')}`
    default: return `Every ${c.cooldown_days ?? 365} days for matching ${r.entity} records`
  }
}
const act = (a: Rule['actions'][number]) => ({ assign_owner: 'Assign owner', create_task: `Create task: “${a.params.subject}”`, apply_cadence: 'Apply a cadence', create_lead: 'Create a seller lead', notify: `Notify: “${a.params.message}”`, set_field: `Set ${a.params.field} = ${a.params.value}` }[a.type] ?? a.type)

export default function Automation() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const { data, isLoading } = useApi<{ items: Rule[] }>('/rules')
  const toggle = useSend<{ id: number; enabled: boolean }>('PATCH', (b) => `/rules/${b.id}`)
  const manage = !!user && ['admin', 'manager'].includes(user.role)
  const [view, setView] = useState<{ kind: 'preview' | 'log' | 'run'; rule: Rule; data: unknown } | null>(null)
  const [err, setErr] = useState('')
  const open = async (kind: 'preview' | 'log' | 'run', rule: Rule) => {
    setErr('')
    try {
      const d = kind === 'preview' ? await api(`/rules/${rule.id}/preview`, { method: 'POST' }) : kind === 'run' ? await api(`/rules/${rule.id}/run`, { method: 'POST' }) : await api(`/rules/${rule.id}/log`)
      setView({ kind, rule, data: d })
      if (kind === 'run') qc.invalidateQueries()
    } catch (e) { setErr((e as Error).message) }
  }
  return (
    <div className="rise">
      <PageHeader title="Automation" subtitle="Small, reviewed rules that create tasks, leads and alerts. They never send email, and every action is audited with the rule as the actor." actions={manage ? <NewRule /> : undefined} />
      {err && <div className="mb-3"><ErrorBox error={new Error(err)} /></div>}
      {isLoading ? <Loading /> : <div className="grid gap-4 lg:grid-cols-2" data-testid="rules">{data?.items.map((r) => (
        <Card key={r.id} className={r.enabled ? '' : 'opacity-60'}><CardContent className="pt-5">
          <div className="flex items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 font-display text-lg font-semibold"><Zap className="h-4 w-4 text-accent" />{r.name}</h3><p className="text-sm text-muted-foreground">{r.description}</p></div>
            <Button size="sm" variant={r.enabled ? 'default' : 'outline'} disabled={!manage} aria-label={`${r.enabled ? 'Disable' : 'Enable'} ${r.name}`} onClick={() => toggle.mutate({ id: r.id, enabled: !r.enabled }, { onSuccess: () => qc.invalidateQueries() })}>{r.enabled ? 'On' : 'Off'}</Button></div>
          <div className="mt-3 rounded-md bg-muted/60 p-3 text-sm"><div><b>When:</b> {trig(r)}</div>{r.conditions && r.conditions.conditions.length > 0 && <div><b>Only if:</b> {r.conditions.conditions.length} condition{r.conditions.conditions.length > 1 ? 's' : ''} match</div>}
            <div className="mt-1"><b>Then:</b><ul className="ml-4 list-disc">{r.actions.map((a, i) => <li key={i}>{act(a)}</li>)}</ul></div></div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{r.actions_logged} actions taken</span>{r.last_run && <span>· last run {fmtDate(r.last_run.at)} ({r.last_run.matched} matched)</span>}<span>· owner {r.owner}</span></div>
          <div className="mt-3 flex gap-2"><Button size="sm" variant="outline" onClick={() => open('preview', r)}><Eye className="h-4 w-4" /> Preview</Button><Button size="sm" variant="outline" onClick={() => open('log', r)}><ScrollText className="h-4 w-4" /> Action log</Button>
            {user?.role === 'admin' && <Button size="sm" variant="accent" onClick={() => open('run', r)}><Play className="h-4 w-4" /> Run now</Button>}</div>
        </CardContent></Card>))}</div>}
      <Dialog open={!!view} onOpenChange={(o) => !o && setView(null)}><DialogContent className="max-w-xl">{view && <Result v={view} />}</DialogContent></Dialog>
    </div>
  )
}

function Result({ v }: { v: { kind: string; rule: Rule; data: unknown } }) {
  const d = v.data as { matched?: number; actions_taken?: number; skipped?: number; sample?: { label?: string; action?: string; result?: string }[]; items?: { at: string; action: string; entity: string; entity_id: number; result: string }[]; actions?: number }
  return (
    <>
      <DialogTitle>{v.kind === 'preview' ? 'Preview' : v.kind === 'run' ? 'Run result' : 'Action log'}: {v.rule.name}</DialogTitle>
      <DialogDescription>{v.kind === 'preview' ? 'A dry run. Nothing was written.' : v.kind === 'run' ? 'The rule ran now. Repeating it does nothing: actions are idempotent.' : 'The most recent actions this rule has taken.'}</DialogDescription>
      {d.matched !== undefined && <p className="mt-3 text-sm"><b data-testid="rule-matched">{d.matched}</b> records matched{d.actions_taken !== undefined && <> · <b>{d.actions_taken}</b> actions taken · {d.skipped} skipped</>}{d.actions !== undefined && <> · {d.actions} actions</>}</p>}
      <ul className="mt-2 max-h-72 divide-y overflow-y-auto text-sm" data-testid="rule-detail">
        {d.sample?.map((s, i) => <li key={i} className="py-1.5">{s.label} {s.action && <span className="text-muted-foreground">· {s.action}: {s.result}</span>}</li>)}
        {d.items?.map((s, i) => <li key={i} className="py-1.5"><span className="text-muted-foreground">{fmtDate(s.at)} · {s.entity} #{s.entity_id}</span> {s.action}: {s.result}</li>)}
        {(d.sample?.length === 0 || d.items?.length === 0) && <li className="py-3 text-muted-foreground">Nothing yet.</li>}</ul>
    </>
  )
}

function NewRule() {
  const qc = useQueryClient()
  const users = useUsers()
  const meta = useApi<Meta>('/rules/meta')
  const cads = useApi<{ id: number; name: string; record_type: string }[]>('/cadences')
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: '', description: '', entity: 'property', trigger_type: 'scheduled', field: 'hold_intent', to: 'selling_soon', to_stage: 'under_contract', date_field: 'loan_maturity_date', offset: '-180', grace: '30', cooldown: '90' })
  const [useCond, setUseCond] = useState(false)
  const [cond, setCond] = useState<Group>({ op: 'and', conditions: [] })
  const [actions, setActions] = useState<{ type: string; params: Record<string, unknown> }[]>([{ type: 'create_task', params: { subject: 'Follow up on {name}', days_due: 1, type: 'call', priority: 'normal' } }])
  const [err, setErr] = useState('')
  const fields = useApi<{ fields: FieldMeta[] }>('/filter-fields', { entity: f.entity }, { enabled: open && useCond })
  const create = useSend<object>('POST', '/rules')
  const cfg = () => {
    switch (f.trigger_type) {
      case 'field_changed': return { field: f.field, ...(f.to ? { to: f.to } : {}) }
      case 'stage_changed': return { to_stage: f.to_stage }
      case 'date_reached': return { date_field: f.date_field, offset_days: Number(f.offset), grace_days: Number(f.grace) }
      case 'scheduled': return { cooldown_days: Number(f.cooldown) }
      default: return {}
    }
  }
  const setAct = (i: number, a: { type: string; params: Record<string, unknown> }) => setActions(actions.map((x, j) => (j === i ? a : x)))
  const defaults: Record<string, Record<string, unknown>> = {
    assign_owner: { user_id: users.data?.[0]?.id }, create_task: { subject: '', days_due: 1, type: 'call', priority: 'normal' }, apply_cadence: { cadence_id: cads.data?.[0]?.id }, create_lead: {}, notify: { message: '', user: 'owner' },
    set_field: { field: Object.keys(meta.data?.set_field[f.entity] ?? {})[0], value: Object.values(meta.data?.set_field[f.entity] ?? {})[0]?.[0] },
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="accent"><Plus className="h-4 w-4" /> New rule</Button></DialogTrigger>
      <DialogContent className="max-w-2xl"><DialogTitle>New rule</DialogTitle><DialogDescription>When something happens, if conditions match, do a small reviewed action.</DialogDescription>
        <div className="mt-4 grid gap-4">
          <div className="grid grid-cols-2 gap-3"><Field label="Name"><Input aria-label="Rule name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Applies to"><Select className="w-full" aria-label="Rule entity" value={f.entity} onChange={(e) => setF({ ...f, entity: e.target.value })}>{meta.data?.entities.map((x) => <option key={x}>{x}</option>)}</Select></Field></div>
          <div className="rounded-lg border p-3"><div className="mb-2 text-sm font-semibold">When</div>
            <Select className="w-full" aria-label="Trigger" value={f.trigger_type} onChange={(e) => setF({ ...f, trigger_type: e.target.value })}>{[['record_created', 'a record is created'], ['field_changed', 'a field changes'], ['stage_changed', 'a deal changes stage'], ['date_reached', 'a date is reached'], ['scheduled', 'on a schedule, for matching records']].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
            <div className="mt-2 flex flex-wrap gap-2">
              {f.trigger_type === 'field_changed' && <><Input aria-label="Field" className="w-44" value={f.field} onChange={(e) => setF({ ...f, field: e.target.value })} /><Input aria-label="Changes to" className="w-44" placeholder="to value (optional)" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></>}
              {f.trigger_type === 'stage_changed' && <Input aria-label="To stage" className="w-56" value={f.to_stage} onChange={(e) => setF({ ...f, to_stage: e.target.value })} />}
              {f.trigger_type === 'date_reached' && <><Select aria-label="Date field" value={f.date_field} onChange={(e) => setF({ ...f, date_field: e.target.value })}>{(meta.data?.date_fields[f.entity] ?? []).map((x) => <option key={x}>{x}</option>)}</Select>
                <Input aria-label="Offset days" type="number" className="w-24" value={f.offset} onChange={(e) => setF({ ...f, offset: e.target.value })} /><span className="self-center text-xs text-muted-foreground">days (negative = before), window</span><Input aria-label="Grace days" type="number" className="w-20" value={f.grace} onChange={(e) => setF({ ...f, grace: e.target.value })} /></>}
              {f.trigger_type === 'scheduled' && <><span className="self-center text-sm">Repeat at most every</span><Input aria-label="Cooldown days" type="number" className="w-24" value={f.cooldown} onChange={(e) => setF({ ...f, cooldown: e.target.value })} /><span className="self-center text-sm">days per record</span></>}</div></div>
          <div className="rounded-lg border p-3"><label className="mb-2 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={useCond} onChange={(e) => setUseCond(e.target.checked)} /> Only if conditions match</label>
            {useCond && (fields.data ? <GroupEditor fields={fields.data.fields} g={cond} onChange={setCond} /> : <Loading />)}</div>
          <div className="rounded-lg border p-3"><div className="mb-2 text-sm font-semibold">Then</div><div className="space-y-2">{actions.map((a, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 p-2">
              <Select aria-label={`Action ${i + 1}`} value={a.type} onChange={(e) => setAct(i, { type: e.target.value, params: defaults[e.target.value] ?? {} })}>{meta.data?.actions.map((x) => <option key={x} value={x}>{x.replace(/_/g, ' ')}</option>)}</Select>
              {a.type === 'create_task' && <><Input aria-label="Task subject" className="w-64" placeholder="Subject ({name} = record)" value={String(a.params.subject ?? '')} onChange={(e) => setAct(i, { ...a, params: { ...a.params, subject: e.target.value } })} /><Input aria-label="Days until due" type="number" className="w-20" value={String(a.params.days_due ?? 0)} onChange={(e) => setAct(i, { ...a, params: { ...a.params, days_due: Number(e.target.value) } })} /></>}
              {a.type === 'notify' && <Input aria-label="Notification message" className="w-72" value={String(a.params.message ?? '')} onChange={(e) => setAct(i, { ...a, params: { ...a.params, message: e.target.value } })} />}
              {a.type === 'assign_owner' && <Select aria-label="Assign to" value={String(a.params.user_id ?? '')} onChange={(e) => setAct(i, { ...a, params: { user_id: Number(e.target.value) } })}>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select>}
              {a.type === 'apply_cadence' && <Select aria-label="Cadence" value={String(a.params.cadence_id ?? '')} onChange={(e) => setAct(i, { ...a, params: { cadence_id: Number(e.target.value) } })}>{cads.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}
              {a.type === 'set_field' && <><Select aria-label="Set field" value={String(a.params.field ?? '')} onChange={(e) => setAct(i, { ...a, params: { field: e.target.value, value: meta.data?.set_field[f.entity][e.target.value][0] } })}>{Object.keys(meta.data?.set_field[f.entity] ?? {}).map((x) => <option key={x}>{x}</option>)}</Select>
                <Select aria-label="Set value" value={String(a.params.value ?? '')} onChange={(e) => setAct(i, { ...a, params: { ...a.params, value: e.target.value } })}>{(meta.data?.set_field[f.entity][String(a.params.field)] ?? []).map((x) => <option key={x}>{x}</option>)}</Select></>}
              <Button size="icon" variant="ghost" aria-label="Remove action" onClick={() => setActions(actions.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button></div>))}</div>
            <Button size="sm" variant="ghost" className="mt-2" onClick={() => setActions([...actions, { type: 'notify', params: { message: '', user: 'owner' } }])}><Plus className="h-3.5 w-3.5" /> Action</Button></div>
          {err && <ErrorBox error={new Error(err)} />}
          <Button disabled={!f.name} onClick={() => { setErr(''); create.mutate({ name: f.name, description: f.description || undefined, entity: f.entity, trigger_type: f.trigger_type, trigger_config: cfg(), conditions: useCond ? clean(cond) : undefined, actions }, { onSuccess: () => { setOpen(false); qc.invalidateQueries() }, onError: (e) => setErr((e as Error).message) }) }}>Create rule</Button>
        </div></DialogContent>
    </Dialog>
  )
}
