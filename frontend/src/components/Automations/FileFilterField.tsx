import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import PathField from './PathField'
import type { FileFilter } from '@/types/api'

type Props = Readonly<{
  value: FileFilter
  onChange: (f: FileFilter) => void
  scopePath?: string
}>

const FILTER_OPTIONS: { label: string; value: FileFilter['type'] }[] = [
  { label: 'All video files', value: 'all' },
  { label: 'Files in a sub-folder…', value: 'subfolder' },
  { label: 'Files whose name contains…', value: 'name_contains' },
]

const HELPER_TEXT: Record<FileFilter['type'], string> = {
  all: 'Will match all video files in the scanned folder and its subdirectories.',
  subfolder: 'Will only match files inside the specified sub-folder.',
  name_contains: 'Will only match files whose name contains the given text (case-insensitive).',
}

export default function FileFilterField({ value, onChange, scopePath }: Props) {
  const handleTypeChange = (type: FileFilter['type']) => {
    if (type === 'all') onChange({ type: 'all', value: null })
    else onChange({ type, value: '' })
  }

  return (
    <div className="space-y-3">
      {/* Type selector */}
      <Select value={value.type} onValueChange={(v) => handleTypeChange(v as FileFilter['type'])}>
        <SelectTrigger className="w-full h-12 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FILTER_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Conditional sub-input */}
      {value.type === 'name_contains' && (
        <Input
          value={value.value ?? ''}
          onChange={(e) => onChange({ ...value, value: e.target.value })}
          placeholder="e.g. Marshals"
          className="h-12 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg"
        />
      )}

      {value.type === 'subfolder' && (
        <PathField
          value={value.value ?? ''}
          onChange={(path) => onChange({ ...value, value: path })}
          placeholder={scopePath ? `${scopePath}/…` : '/shared/…'}
        />
      )}

      {/* Helper text */}
      <p className="text-xs text-zinc-500">{HELPER_TEXT[value.type]}</p>
    </div>
  )
}
