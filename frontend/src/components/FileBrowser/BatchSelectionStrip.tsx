import { Button } from '@/components/ui/button'

type Props = Readonly<{ count: number; onClear: () => void }>

export default function BatchSelectionStrip({ count, onClear }: Props) {
  return (
    <section
      aria-label="Batch selection"
      className="fixed bottom-0 right-0 left-64 z-30 bg-card border-t border-border px-6 py-2 hidden xl:flex items-center justify-between"
    >
      <p className="text-sm font-semibold text-foreground">
        {count} file{count === 1 ? '' : 's'} selected
      </p>
      <Button variant="outline" onClick={onClear} className="h-8">Clear</Button>
    </section>
  )
}
