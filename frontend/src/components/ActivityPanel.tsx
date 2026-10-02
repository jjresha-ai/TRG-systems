import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Replaced with the live activity timeline in Stage 4.
export function ActivityPanel({ recordType }: { recordType: string; recordId: number }) {
  return (
    <Card><CardHeader><CardTitle>Activity timeline</CardTitle></CardHeader><CardContent>
      <p className="text-sm text-muted-foreground">Coming soon: calls, meetings, notes and tasks for this {recordType} (Stage 4).</p>
    </CardContent></Card>
  )
}
