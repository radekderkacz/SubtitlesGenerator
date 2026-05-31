import { useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import FolderPickerDialog from './FolderPickerDialog'

type Props = Readonly<{
  value: string
  onChange: (path: string) => void
  label?: string
  placeholder?: string
}>

export default function PathField({ value, onChange, label, placeholder }: Props) {
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <div className="space-y-2">
      {label && (
        <p className="text-sm font-medium text-zinc-400 uppercase tracking-wider">{label}</p>
      )}
      <div className="flex items-center gap-2">
        <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-zinc-900 border border-zinc-700 rounded-lg">
          <FolderOpen className="h-4 w-4 text-zinc-500 shrink-0" aria-hidden="true" />
          <Input
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder ?? '/shared/…'}
            className="flex-1 border-0 bg-transparent p-0 h-auto text-sm font-mono text-[#e1e2ec] focus-visible:ring-0 focus-visible:ring-offset-0"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setDialogOpen(true)}
          className="shrink-0 bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-zinc-300 hover:text-zinc-100 text-xs font-semibold"
          aria-label="Browse for folder"
        >
          Browse…
        </Button>
      </div>

      <FolderPickerDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        currentPath={value || undefined}
        onSelect={(path) => {
          onChange(path)
          setDialogOpen(false)
        }}
      />
    </div>
  )
}
