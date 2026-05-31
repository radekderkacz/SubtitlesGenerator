import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus, Trash2, ArrowRight } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import SectionHeader from '@/components/Settings/SectionHeader'
import type { Settings, BackendProfile } from '@/types/api'

type Props = Readonly<{
  // SavedConfigurationsPane is a list editor — no in-tab form to be dirty. Prop kept
  // optional for tab consistency; never invoked.
  onDirtyChange?: (isDirty: boolean) => void
}>

const PROFILE_FIELDS = [
  'transcription_api_url',
  'transcription_model',
  'transcription_api_key',
  'translation_provider',
  'translation_model',
  'translation_api_url',
  'translation_api_key',
] as const

function snapshotFromSettings(settings: Settings, name: string): BackendProfile {
  const snap: BackendProfile = { name }
  for (const f of PROFILE_FIELDS) {
    const v = settings[f] as string | null | undefined
    if (v) snap[f] = v
  }
  return snap
}

export default function SavedConfigurationsPane(_props: Props) {
  // No use of _props — see Props comment. Underscored to signal intent.
  const [newName, setNewName] = useState('')

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })
  const profiles: BackendProfile[] = settings?.profiles ?? []

  const updateProfiles = useMutation({
    mutationFn: (next: BackendProfile[]) =>
      apiFetch<{ status: string }>('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify({ profiles: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: () => toast.error('Failed to update profiles'),
  })

  const applyProfile = useMutation({
    mutationFn: (profile: BackendProfile) => {
      const payload: Record<string, string | null> = {}
      for (const f of PROFILE_FIELDS) {
        payload[f] = profile[f] ?? null
      }
      return apiFetch<{ status: string }>('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
    onSuccess: (_r, profile) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      toast.success(`Applied "${profile.name}"`)
    },
    onError: () => toast.error('Failed to apply profile'),
  })

  const handleSaveCurrent = () => {
    const name = newName.trim()
    if (!name) {
      toast.error('Profile name is required')
      return
    }
    if (!settings) return
    if (profiles.some((p) => p.name === name)) {
      toast.error(`A profile named "${name}" already exists`)
      return
    }
    const snap = snapshotFromSettings(settings, name)
    updateProfiles.mutate([...profiles, snap], {
      onSuccess: () => {
        toast.success(`Saved "${name}"`)
        setNewName('')
      },
    })
  }

  const handleDelete = (name: string) => {
    updateProfiles.mutate(profiles.filter((p) => p.name !== name), {
      onSuccess: () => toast.success(`Deleted "${name}"`),
    })
  }

  return (
    <div data-testid="pane-saved-configurations">
      <SectionHeader
        title="Saved Configurations"
        description="Reusable backend profiles selected when submitting a job."
        status="idle"
      />
      <div className="flex flex-col gap-6 max-w-[900px]">
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="p-6 border-b border-border">
            <h2 className="text-base font-semibold text-foreground">Backend Profiles</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Snapshot the current AI Backends configuration under a name so you
              can switch between setups (e.g. <em>Homelab Local</em> vs{' '}
              <em>OpenAI Paid</em>) without retyping URLs and keys each time.
              {' '}
              <strong>Apply</strong>
              {' '}
              copies a saved profile into the active Settings; submitted jobs
              always use whatever Settings has at the moment of submission.
            </p>
          </div>

          <div className="p-6 flex flex-col gap-3 border-b border-border">
            <Label htmlFor="new-profile-name" className="text-xs uppercase tracking-wider text-muted-foreground">
              Save the current AI Backends config as a new profile
            </Label>
            <div className="flex items-center gap-2">
              <Input
                id="new-profile-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Homelab Local"
                className="max-w-sm"
              />
              <Button onClick={handleSaveCurrent} disabled={updateProfiles.isPending || !newName.trim()}>
                <Plus className="h-4 w-4 mr-1" aria-hidden="true" />
                Save profile
              </Button>
            </div>
          </div>

          <div className="p-6">
            {profiles.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                No profiles saved yet. Configure your AI Backends, give the setup
                a name above, and click Save profile.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {profiles.map((p) => (
                  <li
                    key={p.name}
                    className="flex items-center justify-between gap-3 p-3 bg-background border border-border rounded-md"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{p.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                        {summarizeProfile(p)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => applyProfile.mutate(p)}
                        disabled={applyProfile.isPending}
                        className="gap-1"
                      >
                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        Apply
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(p.name)}
                        disabled={updateProfiles.isPending}
                        aria-label={`Delete profile ${p.name}`}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function summarizeProfile(p: BackendProfile): string {
  const parts: string[] = []
  if (p.transcription_api_url) {
    parts.push(`transcribe → ${p.transcription_api_url}`)
  }
  if (p.translation_provider) {
    const modelSuffix = p.translation_model ? ` / ${p.translation_model}` : ''
    parts.push(`translate → ${p.translation_provider}${modelSuffix}`)
  }
  return parts.length > 0 ? parts.join(' · ') : '(empty profile)'
}
