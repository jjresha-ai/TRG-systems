import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { useSend } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ErrorBox, Field } from '@/components/common'

export function NewProperty() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ address: '', city: '', property_type: 'retail', apn: '', building_sf: '' })
  const [err, setErr] = useState('')
  const m = useSend<unknown, { id: number }>('POST', '/properties', ['/properties'])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="accent"><Plus className="h-4 w-4" /> New property</Button></DialogTrigger>
      <DialogContent>
        <DialogTitle>New property</DialogTitle>
        <DialogDescription>APN plus county and normalized address are checked for duplicates.</DialogDescription>
        <form className="mt-4 grid grid-cols-2 gap-3" onSubmit={(e) => {
          e.preventDefault(); setErr('')
          m.mutate({ address: f.address, city: f.city, property_type: f.property_type, apn: f.apn || undefined, building_sf: f.building_sf ? Number(f.building_sf) : undefined },
            { onSuccess: (r) => { setOpen(false); nav(`/properties/${r.id}`) }, onError: (x) => setErr((x as Error).message) })
        }}>
          <Field label="Address" className="col-span-2"><Input required value={f.address} onChange={set('address')} /></Field>
          <Field label="City"><Input required value={f.city} onChange={set('city')} /></Field>
          <Field label="Type"><Select className="w-full" value={f.property_type} onChange={set('property_type')}><option>retail</option><option>industrial</option></Select></Field>
          <Field label="APN"><Input value={f.apn} onChange={set('apn')} /></Field>
          <Field label="Building SF"><Input type="number" value={f.building_sf} onChange={set('building_sf')} /></Field>
          {err && <div className="col-span-2"><ErrorBox error={new Error(err)} /></div>}
          <Button type="submit" className="col-span-2" disabled={m.isPending}>Create property</Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
