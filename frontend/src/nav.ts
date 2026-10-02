import { Building2, Users, MapPin, Target, Store, Kanban, CheckSquare, Landmark, PiggyBank, BarChart3, Mail, ListChecks, Upload, ShieldCheck, LayoutDashboard, type LucideIcon } from 'lucide-react'

export interface NavItem { to: string; label: string; icon: LucideIcon; stage: number; group: string }

export const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, stage: 0, group: 'Overview' },
  { to: '/contacts', label: 'Contacts', icon: Users, stage: 1, group: 'Relationships' },
  { to: '/companies', label: 'Companies', icon: Building2, stage: 1, group: 'Relationships' },
  { to: '/properties', label: 'Properties', icon: MapPin, stage: 1, group: 'Relationships' },
  { to: '/prospecting', label: 'Prospecting', icon: Target, stage: 2, group: 'Pipeline' },
  { to: '/listings', label: 'Listings', icon: Store, stage: 2, group: 'Pipeline' },
  { to: '/deals', label: 'Deals', icon: Kanban, stage: 3, group: 'Pipeline' },
  { to: '/tasks', label: 'Tasks & Activity', icon: CheckSquare, stage: 4, group: 'Work' },
  { to: '/investors', label: 'Investors', icon: Landmark, stage: 5, group: '1880 Capital' },
  { to: '/funds', label: 'Funds', icon: PiggyBank, stage: 5, group: '1880 Capital' },
  { to: '/reports', label: 'Reports', icon: BarChart3, stage: 6, group: 'Insight' },
  { to: '/inbox', label: 'Email', icon: Mail, stage: 7, group: 'Platform' },
  { to: '/lists', label: 'Lists & Views', icon: ListChecks, stage: 7, group: 'Platform' },
  { to: '/data', label: 'Import / Export', icon: Upload, stage: 7, group: 'Platform' },
  { to: '/admin', label: 'Admin & Audit', icon: ShieldCheck, stage: 7, group: 'Platform' },
]
