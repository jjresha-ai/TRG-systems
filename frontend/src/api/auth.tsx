import { createContext, useContext, useState, type ReactNode } from 'react'
import { api, getToken, setToken } from './client'

export interface User { id: number; email: string; name: string; role: string; title?: string | null; team?: string | null }

interface AuthCtx { user: User | null; login: (email: string, password: string) => Promise<void>; logout: () => void }
const Ctx = createContext<AuthCtx>(null as never)
const USER_KEY = 'trg_user'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    try { return getToken() ? JSON.parse(localStorage.getItem(USER_KEY) ?? 'null') : null } catch { return null }
  })
  const login = async (email: string, password: string) => {
    const r = await api<{ token: string; user: User }>('/auth/login', { method: 'POST', body: { email, password } })
    setToken(r.token)
    localStorage.setItem(USER_KEY, JSON.stringify(r.user))
    setUser(r.user)
  }
  const logout = () => { setToken(null); localStorage.removeItem(USER_KEY); setUser(null) }
  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
