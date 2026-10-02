import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useApi, useSend, useUsers, type Page } from '@/api/hooks'
import { useAuth } from '@/api/auth'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ErrorBox, Loading, Pagination, Stat } from '@/components/common'
import { Link } from 'react-router-dom'
import { ActivityRow, CompleteDialog, type Act } from '@/components/ActivityPanel'
import { useNavigate } from 'react-router-dom'

interface Agenda { overdue: Act[]; today: Act[]; this_week: Act[]; counts: { overdue: number; today: number; this_week: number } }
interface Cadence { id: number; name: string; description: string; record_type: string; steps: { day_offset: number; type: string; subject: string }[] }

const link = (a: Act) => {
  const x = a.associations.find((z) => z.record_type === 'contact') ?? a.associations[0]
  return x ? `/${x.record_type === 'company' ? 'companies' : x.record_type + 's'}/${x.record_id}` : '#'
}

export default function Tasks() {
  const { user } = useAuth()
  const users = useUsers()
  const [who, setWho] = useState<string>('')
  const qc = useQueryClient()
  const agenda = useApi<Agenda>('/agenda', { assignee_id: who || undefined })
  const [done, setDone] = useState<Act | null>(null)
  const refresh = () => qc.invalidateQueries()
  const complete = useSend<{ id: number }>('POST', (b) => `/activities/${b.id}/complete`)
  const finish = (a: Act) => (a.type === 'call' ? setDone(a) : complete.mutate({ id: a.id }, { onSuccess: refresh }))
  const c = agenda.data?.counts
  return (
    <div className="rise">
      <PageHeader title="Tasks & Activity" subtitle="Follow-through is the product. Overdue, today and this week for"
        actions={<Select aria-label="Assignee" value={who} onChange={(e) => setWho(e.target.value)}><option value="">Me ({user?.name})</option>{users.data?.filter((u) => u.id !== (user as { id: number })?.id).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select>} />
      <Tabs defaultValue="agenda">
        <TabsList><TabsTrigger value="agenda">Agenda</TabsTrigger><TabsTrigger value="log">Activity log</TabsTrigger><TabsTrigger value="cadences">Cadences</TabsTrigger></TabsList>
        <TabsContent value="agenda">
          <div className="mb-4 grid grid-cols-3 gap-3"><Stat label="Overdue" value={c?.overdue ?? '—'} className={c && c.overdue > 0 ? 'border-destructive/50' : ''} /><Stat label="Today" value={c?.today ?? '—'} /><Stat label="Next 7 days" value={c?.this_week ?? '—'} /></div>
          {agenda.isLoading ? <Loading /> : (
            <div className="grid gap-4 lg:grid-cols-3">
              {([['Overdue', agenda.data?.overdue], ['Today', agenda.data?.today], ['This week', agenda.data?.this_week]] as const).map(([t, rows]) => (
                <Card key={t} data-testid={`agenda-${t.toLowerCase().replace(' ', '-')}`}><CardHeader className="pb-1"><CardTitle className="text-base">{t} <Badge variant={t === 'Overdue' ? 'destructive' : 'secondary'}>{rows?.length ?? 0}</Badge></CardTitle></CardHeader>
                  <CardContent><div className="divide-y">{rows?.map((a) => (<div key={a.id}><ActivityRow a={a} onComplete={finish} />
                    <Link to={link(a)} className="-mt-1 mb-1 ml-11 block text-xs text-primary hover:underline">{a.associations.map((x) => x.label).slice(0, 2).join(' · ')}</Link></div>))}
                    {rows?.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">Nothing here. Nice.</p>}</div></CardContent></Card>))}
            </div>)}
        </TabsContent>
        <TabsContent value="log"><Log /></TabsContent>
        <TabsContent value="cadences"><Cadences /></TabsContent>
      </Tabs>
      <CompleteDialog act={done} onClose={() => setDone(null)} onDone={refresh} />
    </div>
  )
}

function Log() {
  const nav = useNavigate()
  const [type, setType] = useState('')
  const [status, setStatus] = useState('completed')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useApi<Page<Act>>('/activities', { type, status, q, page, limit: 20, sort: status === 'completed' ? 'done' : 'due' })
  return (
    <Card>
      <div className="flex flex-wrap gap-2 border-b p-4">
        <Input aria-label="Search activity" className="max-w-xs" placeholder="Subject…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <Select aria-label="Type" value={type} onChange={(e) => { setType(e.target.value); setPage(1) }}><option value="">All types</option>{['call', 'email', 'meeting', 'site_visit', 'text', 'other'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</Select>
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="completed">Logged</option><option value="planned">Planned</option><option value="">All</option></Select>
      </div>
      <CardContent className="pt-2">{isLoading ? <Loading /> : error ? <ErrorBox error={error} /> : (<>
        <div className="divide-y">{data!.items.map((a) => <div key={a.id} className="cursor-pointer hover:bg-secondary/40" onClick={() => nav(link(a))}><ActivityRow a={a} /></div>)}</div>
      </>)}</CardContent>
      {data && <Pagination page={page} limit={20} total={data.total} onPage={setPage} />}
    </Card>
  )
}

function Cadences() {
  const { data } = useApi<Cadence[]>('/cadences')
  return (
    <div className="grid gap-4 md:grid-cols-3">{data?.map((c) => (
      <Card key={c.id}><CardHeader><CardTitle>{c.name}</CardTitle><p className="text-sm text-muted-foreground">{c.description}</p></CardHeader><CardContent>
        <ol className="relative ml-2 space-y-3 border-l pl-4">{c.steps.map((s, i) => (<li key={i} className="text-sm"><span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-accent" /><span className="font-semibold">Day {s.day_offset}</span> <span className="capitalize text-muted-foreground">· {s.type}</span><div>{s.subject}</div></li>))}</ol>
        <p className="mt-4 text-xs text-muted-foreground">Apply from any {c.record_type} record to create these tasks.</p></CardContent></Card>))}</div>
  )
}
