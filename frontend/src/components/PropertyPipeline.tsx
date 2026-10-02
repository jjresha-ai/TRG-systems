import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Replaced with live listings and deals for this property in Stages 2 and 3.
export function PropertyPipeline({ propertyId }: { propertyId: number }) {
  return (
    <Card data-property={propertyId}><CardHeader><CardTitle>Listings & deals</CardTitle></CardHeader><CardContent>
      <p className="text-sm text-muted-foreground">Coming soon: listing history, buyer interest and deals for this property (Stages 2–3).</p>
    </CardContent></Card>
  )
}
