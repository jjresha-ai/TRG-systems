import { useState } from 'react'
import { useSend } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { ErrorBox, Field } from '@/components/common'

export interface DealLite {
  id: number; name: string; price: number | null; dd_expiry_date: string | null; lost_reason: string | null
  stage: { id: number; key: string; name: string }
}
export interface StageLite { id: number; key: string; name: string; is_won?: boolean; is_lost?: boolean }

/** What the backend will require for this transition (the backend still enforces it; this only collects the data). */
export function needs(deal: DealLite, to: StageLite) {
  return {
    price: (to.is_won || to.key === 'under_contract') && !deal.price,
    lost: !!to.is_lost && !deal.lost_reason,
    dd: to.key === 'due_diligence' && !deal.dd_expiry_date,
  }
}

export function StageMoveDialog({ deal, to, onClose, onDone }: { deal: DealLite | null; to: StageLite | null; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ price: '', lost_reason: '', dd_expiry_date: '' })
  const [err, setErr] = useState('')
  const m = useSend<object>('POST', `/deals/${deal?.id}/stage`)
  const open = !!deal && !!to
  const n = deal && to ? needs(deal, to) : { price: false, lost: false, dd: false }
  const submit = () => {
    setErr('')
    m.mutate({ stage_id: to!.id, price: f.price ? Number(f.price) : undefined, lost_reason: f.lost_reason || undefined, dd_expiry_date: f.dd_expiry_date || undefined }, {
      onSuccess: () => { onDone(); onClose(); setF({ price: '', lost_reason: '', dd_expiry_date: '' }) }, onError: (e) => setErr((e as Error).message),
    })
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose(); setErr('') } }}>
      <DialogContent>
        {deal && to && (<>
          <DialogTitle>Move to {to.name}</DialogTitle>
          <DialogDescription>{deal.name}</DialogDescription>
          <div className="mt-4 grid gap-3">
            {n.price && <Field label="Price"><Input type="number" autoFocus value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} placeholder="Required" /></Field>}
            {n.lost && <Field label="Lost reason"><Input autoFocus value={f.lost_reason} onChange={(e) => setF({ ...f, lost_reason: e.target.value })} placeholder="Required" /></Field>}
            {n.dd && <Field label="Due diligence expiry"><Input type="date" value={f.dd_expiry_date} onChange={(e) => setF({ ...f, dd_expiry_date: e.target.value })} /></Field>}
            {!n.price && !n.lost && !n.dd && <p className="text-sm text-muted-foreground">Confirm moving this deal. Stage history is recorded permanently.</p>}
            {err && <ErrorBox error={new Error(err)} />}
            <Button onClick={submit} disabled={m.isPending}>Move deal</Button>
          </div>
        </>)}
      </DialogContent>
    </Dialog>
  )
}
