import { Search } from 'lucide-react'

// Replaced with the real backend-powered typeahead in Stage 1.
export function GlobalSearch() {
  return (
    <div className="relative w-full max-w-md">
      <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
      <input disabled aria-label="Global search" placeholder="Search contacts, owners, properties — coming soon"
        className="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm placeholder:text-muted-foreground" />
    </div>
  )
}
