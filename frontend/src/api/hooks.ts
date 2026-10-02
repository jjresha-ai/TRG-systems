import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface Page<T> { items: T[]; total: number; page: number; limit: number }

export function useApi<T>(path: string, params?: Record<string, unknown>, opts: { enabled?: boolean; refetchInterval?: number } = {}) {
  return useQuery({ queryKey: [path, params], queryFn: () => api<T>(path, { params }), ...opts })
}

export function useSend<TBody = unknown, TRes = unknown>(method: 'POST' | 'PATCH' | 'DELETE' | 'PUT', path: string | ((b: TBody) => string), invalidate: string[] = []) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TBody) => api<TRes>(typeof path === 'function' ? path(body) : path, { method, body: method === 'DELETE' ? undefined : body }),
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith(k) })),
  })
}

export const useUsers = () => useApi<{ id: number; name: string; role: string }[]>('/auth/users')
