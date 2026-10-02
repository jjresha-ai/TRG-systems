import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { UserPlus } from 'lucide-react'
import { useApi, useSend, type Page } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Table, THead, TBody, TR, TH, TD } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EntityLink, ErrorBox, Field, Loading, Stat } from '@/components/common'
import { compactMoney, cn, fmtDate, money } from '@/lib/utils'
import { StatusBadge, type ListingRow } from '@/pages/Listings'
import type { ContactRow } from '@/pages/Contacts'
import { ActivityPanel } from '@/components/ActivityPanel'

const STAGES = ['inquiry', 'ca_sent', 'ca_signed', 'om_sent', 'tour', 'offer', 'declined']
const STAGE_LABEL: Record<string, string> = { inquiry: 'Inquiry', ca_sent: 'CA sent', ca_signed: 'CA signed', om_sent: 'OM sent', tour: 'Tour', offer: 'Offer', declined: 'Declined' }
const NEXT: Record<string, string[]> = {
  prospect: ['active', 'withdrawn'], active: ['under_contract', 'expired', 'withdrawn'], under_contract: ['closed', 'active', 'withdrawn'], closed: [], expired: ['active'], withdrawn: ['prospect', 'active'],
}
interface Interest { id: number; contact_id: number | null; contact: string; company: string | null; stage: string; offer_amount: number | null; channel: string; last_at: string | null; declined_reason: string | null }

export default function ListingDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: l, isLoading, error } = useApi<ListingRow>(`/listings/${id}`)
  const interest = useApi<{ items: Interest[]; funnel: Record<string, number>; total: number }>(`/listings/${id}/interest`)
  const [err, setErr] = useState('')
  const [dlg, setDlg] = useState<{ kind: 'activate' | 'close' | null }>({ kind: null })
  const status = useSend<Record<string, unknown> & { status: string }>('POST', `/listings/${id}/status`)
  const event = useSend<{ iid: number; stage: string; amount?: number }>('POST', (b) => `/interest/${b.iid}/events`)
  const refresh = () => qc.invalidateQueries()
  if (isLoading) return <Loading />
  if (error || !l) return <ErrorBox error={error} />
  const move = (to: string) => {
    setErr('')
    if (to === 'active' && (!l.list_price || !l.agreement_date || !l.expiration_date)) return setDlg({ kind: 'activate' })
    if (to === 'closed') return setDlg({ kind: 'close' })
    status.mutate({ status: to }, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) })
  }
  const advance = (i: Interest, stage: string) => {
    setErr('')
    const amount = stage === 'offer' ? Number(window.prompt('Offer amount ($)') ?? 0) : undefined
    if (stage === 'offer' && !amount) return
    event.mutate({ iid: i.id, stage, amount }, { onSuccess: refresh, onError: (e) => setErr((e as Error).message) })
  }
  const max = Math.max(...Object.values(interest.data?.funnel ?? { x: 1 }), 1)
  return (
    <div className="rise">
      <PageHeader title={l.property_name ?? l.address} subtitle={`${l.property_name ? l.address + ', ' : ''}${l.city} · ${l.subtype ?? l.property_type} · Seller: ${l.seller_company ?? l.seller_contact ?? '—'}`}
        actions={<><StatusBadge s={l.status} />{NEXT[l.status].map((n) => <Button key={n} size="sm" variant={n === 'active' || n === 'under_contract' || n === 'closed' ? 'default' : 'outline'} onClick={() => move(n)} className="capitalize">{n === 'under_contract' ? 'Go under contract' : n === 'closed' ? 'Close' : `Mark ${n.replace('_', ' ')}`}</Button>)}</>} />
      {err && <div className="mb-4"><ErrorBox error={new Error(err)} /></div>}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={l.status === 'closed' ? 'Sold price' : 'List price'} value={l.status === 'closed' ? compactMoney(l.sold_price) : compactMoney(l.list_price)} hint={l.price_per_sf ? `$${l.price_per_sf}/SF` : undefined} />
        <Stat label="Cap rate" value={l.cap_rate_bps ? `${(l.cap_rate_bps / 100).toFixed(2)}%` : '—'} />
        <Stat label="Days on market" value={l.days_on_market ?? '—'} hint={l.active_date ? `Active ${fmtDate(l.active_date)}` : 'Not yet active'} />
        <Stat label="Expires" value={l.expiration_date ? fmtDate(l.expiration_date) : '—'} hint={l.days_to_expiration != null ? `${l.days_to_expiration} days` : undefined} className={l.days_to_expiration != null && l.days_to_expiration <= 60 && l.status === 'active' ? 'border-warning/60' : ''} />
        {l.expected_commission != null ? <Stat label="Expected commission" value={compactMoney(l.expected_commission)} hint={`${((l.commission_rate_bps ?? 0) / 100).toFixed(2)}% of price`} /> : <Stat label="Commission" value="Restricted" hint="Your role cannot view fees" />}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><div className="flex items-center justify-between"><CardTitle>Buyer interest</CardTitle><AddBuyer listingId={l.id} onDone={refresh} /></div></CardHeader><CardContent>
            <div className="mb-4 grid grid-cols-7 gap-1.5" aria-label="Buyer funnel">
              {STAGES.map((s) => (<div key={s} className="text-center"><div className="flex h-20 items-end justify-center rounded bg-muted"><div className={cn('w-full rounded-t', s === 'declined' ? 'bg-destructive/60' : 'bg-accent')} style={{ height: `${((interest.data?.funnel[s] ?? 0) / max) * 100}%`, minHeight: (interest.data?.funnel[s] ?? 0) ? 4 : 0 }} /></div>
                <div className="mt-1 font-display text-lg font-semibold">{interest.data?.funnel[s] ?? 0}</div><div className="text-[10px] uppercase tracking-wide text-muted-foreground">{STAGE_LABEL[s]}</div></div>))}
            </div>
            {!interest.data ? <Loading /> : interest.data.items.length === 0 ? <p className="text-sm text-muted-foreground">No buyer interest recorded yet.</p> : (
              <Table><THead><TR><TH>Buyer</TH><TH>Stage</TH><TH className="text-right">Offer</TH><TH>Via</TH><TH>Move to</TH></TR></THead>
                <TBody>{interest.data.items.map((i) => (
                  <TR key={i.id}><TD>{i.contact_id ? <EntityLink to={`/contacts/${i.contact_id}`}>{i.contact}</EntityLink> : <span className="italic text-muted-foreground">{i.contact}</span>}{i.company && <div className="text-xs text-muted-foreground">{i.company}</div>}</TD>
                    <TD><Badge variant={i.stage === 'offer' ? 'accent' : i.stage === 'declined' ? 'destructive' : 'secondary'}>{STAGE_LABEL[i.stage]}</Badge>{i.declined_reason && <div className="text-xs text-muted-foreground">{i.declined_reason}</div>}</TD>
                    <TD className="text-right tabular-nums">{i.offer_amount ? money(i.offer_amount) : '—'}</TD><TD className="capitalize text-muted-foreground">{i.channel}</TD>
                    <TD>{i.stage !== 'declined' && <Select aria-label={`Move ${i.contact}`} value="" onChange={(e) => e.target.value && advance(i, e.target.value)} className="h-8 text-xs"><option value="">Advance…</option>{STAGES.filter((s) => STAGES.indexOf(s) > STAGES.indexOf(i.stage) || s === 'declined').map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}</Select>}</TD></TR>))}
                </TBody></Table>)}
          </CardContent></Card>
          <ActivityPanel recordType="listing" recordId={l.id} />
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Broker team</CardTitle></CardHeader><CardContent><ul className="space-y-2 text-sm">{l.brokers.map((b) => (<li key={b.user_id} className="flex justify-between"><span>{b.name} <span className="text-xs capitalize text-muted-foreground">{b.role}</span></span><Badge variant="outline">{b.split_pct}%</Badge></li>))}</ul></CardContent></Card>
          <Card><CardHeader><CardTitle>Listing agreement</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Signed</span><span>{fmtDate(l.agreement_date)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Expires</span><span>{fmtDate(l.expiration_date)}</span></div>
            {l.commission_terms && <div className="border-t pt-2 text-xs text-muted-foreground">{l.commission_terms}</div>}
            <div className="border-t pt-2"><EntityLink to={`/properties/${l.property_id}`}>Open property record →</EntityLink></div>
          </CardContent></Card>
        </div>
      </div>
      <ActivateDialog open={dlg.kind === 'activate'} l={l} onClose={() => setDlg({ kind: null })} onDone={refresh} />
      <CloseDialog open={dlg.kind === 'close'} l={l} onClose={() => setDlg({ kind: null })} onDone={refresh} />
    </div>
  )
}

function ActivateDialog({ open, l, onClose, onDone }: { open: boolean; l: ListingRow; onClose: () => void; onDone: () => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const [f, setF] = useState({ list_price: String(l.list_price ?? ''), agreement_date: l.agreement_date ?? today, expiration_date: l.expiration_date ?? '' })
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', `/listings/${l.id}/status`)
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}><DialogContent>
      <DialogTitle>Activate listing</DialogTitle><DialogDescription>Only one active sale listing is allowed per property.</DialogDescription>
      <div className="mt-4 grid gap-3">
        <Field label="List price"><Input type="number" value={f.list_price} onChange={(e) => setF({ ...f, list_price: e.target.value })} /></Field>
        <Field label="Agreement date"><Input type="date" value={f.agreement_date} onChange={(e) => setF({ ...f, agreement_date: e.target.value })} /></Field>
        <Field label="Expiration date"><Input type="date" value={f.expiration_date} onChange={(e) => setF({ ...f, expiration_date: e.target.value })} /></Field>
        {err && <ErrorBox error={new Error(err)} />}
        <Button onClick={() => m.mutate({ status: 'active', list_price: Number(f.list_price), agreement_date: f.agreement_date, expiration_date: f.expiration_date }, { onSuccess: () => { onDone(); onClose() }, onError: (e) => setErr((e as Error).message) })}>Activate</Button>
      </div>
    </DialogContent></Dialog>
  )
}

function CloseDialog({ open, l, onClose, onDone }: { open: boolean; l: ListingRow; onClose: () => void; onDone: () => void }) {
  const [price, setPrice] = useState('')
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', `/listings/${l.id}/status`)
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}><DialogContent>
      <DialogTitle>Close listing</DialogTitle><DialogDescription>A sold price is required.</DialogDescription>
      <div className="mt-4 grid gap-3">
        <Field label="Sold price"><Input type="number" value={price} onChange={(e) => setPrice(e.target.value)} /></Field>
        {err && <ErrorBox error={new Error(err)} />}
        <Button onClick={() => m.mutate({ status: 'closed', sold_price: Number(price) }, { onSuccess: () => { onDone(); onClose() }, onError: (e) => setErr((e as Error).message) })}>Close at this price</Button>
      </div>
    </DialogContent></Dialog>
  )
}

function AddBuyer({ listingId, onDone }: { listingId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const found = useApi<Page<ContactRow>>('/contacts', { q, limit: 6 }, { enabled: q.length >= 2 })
  const m = useSend<object>('POST', `/listings/${listingId}/interest`)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm" variant="outline"><UserPlus className="h-4 w-4" /> Add buyer</Button></DialogTrigger>
      <DialogContent><DialogTitle>Add buyer interest</DialogTitle><DialogDescription>Manual entry uses the same service as email and web-form responses.</DialogDescription>
        <div className="mt-4 space-y-3"><Field label="Find contact"><Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, email or phone…" /></Field>
          <ul className="divide-y rounded-md border">{found.data?.items.map((c) => (<li key={c.id}><button className="w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-secondary" onClick={() => m.mutate({ contact_id: c.id, stage: 'inquiry', channel: 'manual' }, { onSuccess: () => { onDone(); setOpen(false) }, onError: (e) => setErr((e as Error).message) })}>{c.full_name} <span className="text-xs text-muted-foreground">· {c.company ?? c.title}</span></button></li>))}</ul>
          {err && <ErrorBox error={new Error(err)} />}</div>
      </DialogContent>
    </Dialog>
  )
}
