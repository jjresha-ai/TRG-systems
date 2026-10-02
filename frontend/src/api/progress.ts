import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface Stage { id: number; name: string; adrs: string; backend: string; frontend: string; blurb: string }

export const useProgress = () =>
  useQuery({ queryKey: ['progress'], queryFn: () => api<{ stages: Stage[] }>('/progress'), refetchInterval: 3000 })
