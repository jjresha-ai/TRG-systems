import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const DEMO = [
  ['jim@resha.group', 'Jim Resha', 'Admin'],
  ['maria@resha.group', 'Maria Delgado', 'Manager'],
  ['kevin@resha.group', 'Kevin Park', 'Broker'],
  ['priya@resha.group', 'Priya Nair', 'Assistant'],
  ['auditor@resha.group', 'Sam Auditor', 'Read-only'],
]

export default function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('jim@resha.group')
  const [password, setPassword] = useState('demo1234')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setError('')
    try { await login(email, password); nav('/') } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden bg-sidebar p-14 text-sidebar-foreground lg:flex lg:flex-col lg:justify-between">
        <div className="grain absolute inset-0 opacity-70" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent font-display text-xl font-bold text-accent-foreground">T</div>
            <span className="font-display text-xl text-white">TRG Systems</span>
          </div>
        </div>
        <div className="relative max-w-lg">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.25em] text-accent">The Resha Group · 1880 Capital</p>
          <h1 className="font-display text-5xl font-semibold leading-[1.05] text-white">Every owner. Every hold-or-sell decision. One system.</h1>
          <p className="mt-6 text-lg text-sidebar-foreground/80">Retail and industrial investment sales across Southern California, built to fill the listing pipeline and close deals.</p>
        </div>
        <p className="relative text-sm text-sidebar-foreground/60">Commercial real estate since 1982.</p>
      </div>
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <h2 className="font-display text-3xl font-semibold">Sign in</h2>
          <p className="mt-1 text-sm text-muted-foreground">Demo accounts use the password <code className="rounded bg-muted px-1">demo1234</code>.</p>
          <form onSubmit={submit} className="mt-6 space-y-3">
            <Input aria-label="Email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
            <Input aria-label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" size="lg" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
          </form>
          <div className="mt-8">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Quick demo logins</p>
            <div className="grid gap-1.5">
              {DEMO.map(([e, n, r]) => (
                <button key={e} type="button" onClick={() => { setEmail(e); setPassword('demo1234') }}
                  className="flex cursor-pointer items-center justify-between rounded-md border bg-card px-3 py-2 text-left text-sm hover:bg-secondary">
                  <span className="font-medium">{n}</span><span className="text-xs text-muted-foreground">{r}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
