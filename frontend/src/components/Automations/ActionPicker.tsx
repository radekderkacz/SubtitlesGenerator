import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Action } from '@/types/api'

type Props = Readonly<{
  value: Action
  onChange: (value: Action) => void
}>

const LANGUAGES = [
  { value: 'auto', label: 'Auto-detect' },
  { value: 'en', label: 'English' },
  { value: 'pl', label: 'Polish' },
  { value: 'de', label: 'German' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'it', label: 'Italian' },
  { value: 'ja', label: 'Japanese' },
  { value: 'zh', label: 'Chinese' },
]

export default function ActionPicker({ value, onChange }: Props) {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<{ profiles?: { name: string }[] }>('/api/v1/settings'),
  })
  const profiles = settings?.profiles ?? []

  return (
    <div className="space-y-3">
      {/* Profile */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Profile</Label>
        <Select
          value={value.profile_name}
          onValueChange={(v: string | null) => onChange({ ...value, profile_name: v ?? '' })}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select profile" />
          </SelectTrigger>
          <SelectContent>
            {profiles.map((p) => (
              <SelectItem key={p.name} value={p.name}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Source language */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Source Language</Label>
        <Select
          value={value.source_language ?? 'auto'}
          onValueChange={(v: string | null) =>
            onChange({ ...value, source_language: !v || v === 'auto' ? null : v })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LANGUAGES.map((l) => (
              <SelectItem key={l.value} value={l.value}>
                {l.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Target language */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Target Language (leave blank to skip translation)</Label>
        <Select
          value={value.target_language ?? 'none'}
          onValueChange={(v: string | null) =>
            onChange({ ...value, target_language: !v || v === 'none' ? null : v })
          }
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">None (transcription only)</SelectItem>
            {LANGUAGES.filter((l) => l.value !== 'auto').map((l) => (
              <SelectItem key={l.value} value={l.value}>
                {l.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
