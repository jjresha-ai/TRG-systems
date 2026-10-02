import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Phone, Mail } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogTrigger } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { ago, ErrorBox, Field, Loading, Pagination, TypeBadge } from '@/components/common'

export interface ContactRow {
  id: number; full_name: string; title: string | null; primary_email: string | null; primary_phone: string | null; company: string | null
  contact_types: string[]; lifecycle_stage: string; owner_name: string | null; last_contact_at: string | null; holdings_count: number | null; do_not_contact: boolean; city: string | null; tags: string[]
}

const TYPES = ['owner', 'buyer', 'investor', 'lender', 'attorney', 'tenant', 'broker']

export default function Contacts() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [lifecycle, setLifecycle] = useState('')
  const [stale, setStale] = useState('')
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useApi<Page<ContactRow>>('/contacts', { q, type, lifecycle, stale_days: stale, page, limit: 25 })
  const reset = (fn: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { fn(e.target.value); setPage(1) }

  return (
    <div className="rise">
      <PageHeader title="Contacts" subtitle={data ? `${data.total.toLocaleString()} people across owners, buyers, investors and lenders` : undefined} actions={<NewContact />} />
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-4">
          <Input aria-label="Filter contacts" className="max-w-xs" placeholder="Name, title, email, phone…" value={q} onChange={reset(setQ)} />
          <Select aria-label="Type" value={type} onChange={reset(setType)}><option value="">All types</option>{TYPES.map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}</Select>
          <Select aria-label="Lifecycle" value={lifecycle} onChange={reset(setLifecycle)}>
            <option value="">Any stage</option>
            {['prospect', 'active_relationship', 'client', 'past_client', 'inactive'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
          </Select>
          <Select aria-label="Recency" value={stale} onChange={reset(setStale)}><option value="">Any recency</option><option value="90">Untouched 90+ days</option><option value="180">Untouched 180+ days</option></Select>
        </div>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (
          <>
            <Table>
              <THead><TR><TH>Name</TH><TH>Company</TH><TH>Type</TH><TH>Stage</TH><TH>Broker</TH><TH>Last contact</TH><TH className="text-right">Properties</TH></TR></THead>
              <TBody>
                {data!.items.map((c) => (
                  <TR key={c.id} className="cursor-pointer" onClick={() => nav(`/contacts/${c.id}`)}>
                    <TD>
                      <div className="flex items-center gap-2 font-medium">{c.full_name}{c.do_not_contact && <Badge variant="destructive">DNC</Badge>}</div>
                      <div className="flex gap-3 text-xs text-muted-foreground">{c.title}
                        {c.primary_phone && <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" />{c.primary_phone}</span>}
                        {c.primary_email && <span className="hidden items-center gap-1 xl:inline-flex"><Mail className="h-3 w-3" />{c.primary_email}</span>}
                      </div>
                    </TD>
                    <TD>{c.company ?? <span className="text-muted-foreground">—</span>}</TD>
                    <TD><div className="flex flex-wrap gap-1">{c.contact_types.map((t) => <TypeBadge key={t} t={t} />)}</div></TD>
                    <TD className="capitalize text-muted-foreground">{c.lifecycle_stage.replace('_', ' ')}</TD>
                    <TD>{c.owner_name}</TD>
                    <TD className="text-muted-foreground">{ago(c.last_contact_at)}</TD>
                    <TD className="text-right tabular-nums">{c.holdings_count || '—'}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} limit={25} total={data!.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  )
}

function NewContact() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ first_name: '', last_name: '', title: '', email: '', phone: '', type: 'owner' })
  const [err, setErr] = useState<string>('')
  const m = useSend<unknown, { id: number }>('POST', '/contacts', ['/contacts'])
  const submit = (e: React.FormEvent) => {
    e.preventDefault(); setErr('')
    m.mutate({ first_name: f.first_name, last_name: f.last_name, title: f.title || null, contact_types: [f.type],
      emails: f.email ? [{ email: f.email }] : [], phones: f.phone ? [{ phone: f.phone }] : [] }, {
      onSuccess: (r) => { setOpen(false); nav(`/contacts/${r.id}`) },
      onError: (e) => {
        const msg = (e as Error).message
        setErr(msg.includes('matches') ? 'Possible duplicate: this email or phone already belongs to a contact. ' + msg : msg)
      },
    })
  }
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="accent"><Plus className="h-4 w-4" /> New contact</Button></DialogTrigger>
      <DialogContent>
        <DialogTitle>New contact</DialogTitle>
        <DialogDescription>Duplicates are checked against email and phone before saving.</DialogDescription>
        <form onSubmit={submit} className="mt-4 grid grid-cols-2 gap-3">
          <Field label="First name"><Input required value={f.first_name} onChange={set('first_name')} /></Field>
          <Field label="Last name"><Input required value={f.last_name} onChange={set('last_name')} /></Field>
          <Field label="Title" className="col-span-2"><Input value={f.title} onChange={set('title')} /></Field>
          <Field label="Email"><Input type="email" value={f.email} onChange={set('email')} /></Field>
          <Field label="Phone"><Input value={f.phone} onChange={set('phone')} /></Field>
          <Field label="Type" className="col-span-2"><Select className="w-full" value={f.type} onChange={set('type')}>{TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
          {err && <div className="col-span-2"><ErrorBox error={new Error(err)} /></div>}
          <Button type="submit" className="col-span-2" disabled={m.isPending}>{m.isPending ? 'Saving…' : 'Create contact'}</Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
