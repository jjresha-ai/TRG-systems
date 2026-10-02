import { useParams } from 'react-router-dom'
import { AlertTriangle, Building2, Mail, MapPin, Phone } from 'lucide-react'
import { useApi } from '@/api/hooks'
import { PageHeader } from '@/components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ago, EntityLink, ErrorBox, Loading, Stat, TypeBadge } from '@/components/common'
import { fmtDate } from '@/lib/utils'
import { ActivityPanel } from '@/components/ActivityPanel'
import { CustomFieldsCard } from '@/components/CustomFieldsCard'

interface Detail {
  id: number; full_name: string; title: string | null; address: string | null; city: string | null; state: string | null; zip: string | null
  contact_types: string[]; lifecycle_stage: string; owner_name: string | null; last_contact_at: string | null; source: string | null; tags: string[]
  do_not_contact: boolean; do_not_contact_reason: string | null; created_at: string
  emails: { id: number; email: string; label: string; is_primary: boolean }[]; phones: { id: number; phone: string; label: string; is_primary: boolean }[]
  companies: { role_id: number; company_id: number; company: string; kind: string; role: string; is_primary: boolean }[]
  holdings: { property_id: number; address: string; city: string; via: string }[]
  custom: Record<string, unknown>
  possible_duplicates: { id: number; other_id: number; reason: string }[]
}

export default function ContactDetail() {
  const { id } = useParams()
  const { data: c, isLoading, error } = useApi<Detail>(`/contacts/${id}`)
  if (isLoading) return <Loading />
  if (error || !c) return <ErrorBox error={error} />
  return (
    <div className="rise">
      <PageHeader title={c.full_name} subtitle={[c.title, c.companies[0]?.company].filter(Boolean).join(' · ')}
        actions={<div className="flex gap-1">{c.contact_types.map((t) => <TypeBadge key={t} t={t} />)}</div>} />
      {c.do_not_contact && (
        <div role="alert" className="mb-4 flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" /> Do not contact{c.do_not_contact_reason ? `: ${c.do_not_contact_reason}` : ''}. Outreach is blocked by the backend.
        </div>
      )}
      {c.possible_duplicates.length > 0 && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 text-warning" /> Possible duplicate ({c.possible_duplicates[0].reason}). <EntityLink to="/duplicates">Review in Data Quality</EntityLink>
        </div>
      )}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Stage" value={<span className="capitalize">{c.lifecycle_stage.replace('_', ' ')}</span>} />
        <Stat label="Properties" value={c.holdings.length} hint="direct or via entities" />
        <Stat label="Last contact" value={ago(c.last_contact_at)} hint={c.last_contact_at ? fmtDate(c.last_contact_at) : 'No activity logged'} />
        <Stat label="Broker" value={c.owner_name ?? '—'} hint={`Source: ${c.source ?? '—'}`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardTitle>What they own</CardTitle></CardHeader><CardContent>
            {c.holdings.length === 0 ? <p className="text-sm text-muted-foreground">No properties linked yet.</p> : (
              <ul className="divide-y">{c.holdings.map((h) => (
                <li key={h.property_id} className="flex items-center justify-between py-2.5">
                  <div><EntityLink to={`/properties/${h.property_id}`}>{h.address}</EntityLink><div className="text-xs text-muted-foreground">{h.city}</div></div>
                  <Badge variant="outline">{h.via === 'direct' ? 'Direct' : `via ${h.via}`}</Badge>
                </li>))}
              </ul>)}
          </CardContent></Card>
          <ActivityPanel recordType="contact" recordId={c.id} />
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Contact info</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            {c.emails.map((e) => <div key={e.id} className="flex items-center gap-2"><Mail className="h-4 w-4 text-accent" /><a className="hover:underline" href={`mailto:${e.email}`}>{e.email}</a><span className="text-xs text-muted-foreground">{e.label}</span></div>)}
            {c.phones.map((p) => <div key={p.id} className="flex items-center gap-2"><Phone className="h-4 w-4 text-accent" />{p.phone}<span className="text-xs text-muted-foreground">{p.label}</span></div>)}
            {c.address && <div className="flex items-center gap-2"><MapPin className="h-4 w-4 text-accent" />{c.address}, {c.city} {c.state} {c.zip}</div>}
          </CardContent></Card>
          <CustomFieldsCard entity="contact" path={`/contacts/${c.id}`} values={c.custom} />
          <Card><CardHeader><CardTitle>Entities & roles</CardTitle></CardHeader><CardContent>
            {c.companies.length === 0 ? <p className="text-sm text-muted-foreground">No company links.</p> : (
              <ul className="space-y-2">{c.companies.map((r) => (
                <li key={r.role_id} className="flex items-start gap-2 text-sm"><Building2 className="mt-0.5 h-4 w-4 text-accent" />
                  <div><EntityLink to={`/companies/${r.company_id}`}>{r.company}</EntityLink><div className="text-xs capitalize text-muted-foreground">{r.role.replace('_', ' ')} · {r.kind.replace('_', ' ')}</div></div></li>))}
              </ul>)}
          </CardContent></Card>
          {c.tags.length > 0 && <div className="flex flex-wrap gap-1.5">{c.tags.map((t) => <Badge key={t} variant="accent">{t}</Badge>)}</div>}
        </div>
      </div>
    </div>
  )
}
