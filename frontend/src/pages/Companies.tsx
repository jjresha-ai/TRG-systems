import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field, Loading, Pagination } from '@/components/common'
import { compactMoney } from '@/lib/utils'

interface Row { id: number; name: string; kind: string; city: string | null; owner_name: string | null; properties_count: number; principals_count: number; portfolio_value: number; tags: string[] }
const KINDS = ['llc', 'trust', 'corporation', 'fund', 'family_office', 'lender', 'brokerage', 'other']

export default function Companies() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useApi<Page<Row>>('/companies', { q, kind, page, limit: 25 })
  return (
    <div className="rise">
      <PageHeader title="Companies & Entities" subtitle={data ? `${data.total} LLCs, trusts, funds, lenders and brokerages` : undefined} actions={<NewCompany />} />
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-4">
          <Input aria-label="Filter companies" className="max-w-xs" placeholder="Entity name…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
          <Select aria-label="Kind" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}><option value="">All kinds</option>{KINDS.map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}</Select>
        </div>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (<>
          <Table>
            <THead><TR><TH>Entity</TH><TH>Kind</TH><TH>City</TH><TH className="text-right">Principals</TH><TH className="text-right">Properties</TH><TH className="text-right">Portfolio value</TH><TH>Broker</TH></TR></THead>
            <TBody>{data!.items.map((c) => (
              <TR key={c.id} className="cursor-pointer" onClick={() => nav(`/companies/${c.id}`)}>
                <TD className="font-medium">{c.name}</TD>
                <TD><Badge variant="secondary" className="capitalize">{c.kind.replace('_', ' ')}</Badge></TD>
                <TD>{c.city}</TD>
                <TD className="text-right tabular-nums">{c.principals_count}</TD>
                <TD className="text-right tabular-nums">{c.properties_count || '—'}</TD>
                <TD className="text-right tabular-nums">{c.portfolio_value ? compactMoney(c.portfolio_value) : '—'}</TD>
                <TD>{c.owner_name}</TD>
              </TR>))}
            </TBody>
          </Table>
          <Pagination page={page} limit={25} total={data!.total} onPage={setPage} />
        </>)}
      </Card>
    </div>
  )
}

function NewCompany() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: '', kind: 'llc', city: '', website: '' })
  const [err, setErr] = useState('')
  const m = useSend<unknown, { id: number }>('POST', '/companies', ['/companies'])
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="accent"><Plus className="h-4 w-4" /> New entity</Button></DialogTrigger>
      <DialogContent>
        <DialogTitle>New company or entity</DialogTitle>
        <DialogDescription>Names are normalized (LLC, L.L.C., Inc. are ignored) to block duplicates.</DialogDescription>
        <form className="mt-4 grid gap-3" onSubmit={(e) => { e.preventDefault(); setErr(''); m.mutate({ ...f, website: f.website || null, city: f.city || null }, { onSuccess: (r) => { setOpen(false); nav(`/companies/${r.id}`) }, onError: (x) => setErr((x as Error).message) }) }}>
          <Field label="Name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Kind"><Select className="w-full" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}</Select></Field>
          <Field label="City"><Input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></Field>
          <Field label="Website"><Input value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} /></Field>
          {err && <ErrorBox error={new Error(err)} />}
          <Button type="submit" disabled={m.isPending}>Create entity</Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
