import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Link } from 'react-router'
import { Sparkles } from 'lucide-react'
import { apiFetch, ApiRequestError } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import { PathInput } from '@/components/PathInput/PathInput'
import SectionHeader from '@/components/Settings/SectionHeader'
import type { Settings } from '@/types/api'

const ALLOWED_PATH_ROOTS = ['/mnt', '/media', '/srv', '/data', '/shared'] as const
const ALLOWED_PATH_PATTERN = /^\/(mnt|media|srv|data|shared)(\/|$)/
const ALLOWED_PATH_MESSAGE = `Path must start with ${ALLOWED_PATH_ROOTS.join(', ')}`

const schema = z.object({
  nas_mount_path: z
    .string()
    .min(1, 'Path is required')
    .regex(ALLOWED_PATH_PATTERN, ALLOWED_PATH_MESSAGE),
  prefer_existing_subs: z.boolean(),
})

type FormValues = z.infer<typeof schema>

type Props = Readonly<{
  onDirtyChange: (isDirty: boolean) => void
}>

export default function NasPathsPane({ onDirtyChange }: Props) {
  const [successPath, setSuccessPath] = useState<string | null>(null)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      nas_mount_path: settings?.nas_mount_path ?? '',
      prefer_existing_subs: settings?.prefer_existing_subs ?? true,
    },
  })

  useEffect(() => {
    if (settings && !form.formState.isDirty) {
      form.reset({
        nas_mount_path: settings.nas_mount_path ?? '',
        prefer_existing_subs: settings.prefer_existing_subs ?? true,
      })
    }
  }, [settings, form])

  const mutation = useMutation({
    mutationFn: (data: FormValues) =>
      apiFetch<{ status: string }>('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      toast('Settings saved', { duration: 2000 })
      form.reset(variables)
      setSuccessPath(variables.nas_mount_path)
    },
    onError: (error) => {
      if (error instanceof ApiRequestError && error.code === 'INVALID_NAS_PATH') {
        form.setError('nas_mount_path', {
          message: 'Path does not exist or is not accessible',
        })
      } else if (error instanceof ApiRequestError && error.code === 'NAS_PATH_NOT_ALLOWED') {
        form.setError('nas_mount_path', { message: ALLOWED_PATH_MESSAGE })
      } else {
        toast.error('Failed to save settings')
      }
    },
  })

  const isDirty = form.formState.isDirty
  useEffect(() => {
    onDirtyChange(isDirty)
    // Clear this section's dirty flag when the pane unmounts (navigating
    // to another section) so the sticky unsaved-changes bar can't keep
    // pointing at a section that is no longer mounted/savable.
    return () => onDirtyChange(false)
  }, [isDirty, onDirtyChange])

  const currentNasPath = form.watch('nas_mount_path')

  function onSubmit(data: FormValues) {
    mutation.mutate(data)
  }

  useEffect(() => {
    const onSave = (e: Event) => {
      if ((e as CustomEvent).detail === 'media') {
        form.handleSubmit(onSubmit)().catch(() => {})
      }
    }
    globalThis.addEventListener('settings:save', onSave)
    return () => globalThis.removeEventListener('settings:save', onSave)
  }, [form, onSubmit])

  return (
    <div data-testid="pane-media">
      <SectionHeader
        title="Media Library"
        description="Where the worker reads videos and writes subtitle files inside the container."
        status="idle"
      />
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-6 max-w-2xl">
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="p-6 border-b border-border">
            <h2 className="text-base font-semibold text-foreground">Library Root</h2>
            <p className="text-sm text-muted-foreground mt-1">
              The path inside the container where your video files are mounted.
              Usually <code className="font-mono">/media</code> (the right-hand side of the
              docker-compose volume mapping). Subtitle files are written next to each video.
            </p>
          </div>
          <div className="p-6 flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="nas_mount_path" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Container Path
              </label>
              <PathInput
                id="nas_mount_path"
                value={currentNasPath}
                onChange={(value) => form.setValue('nas_mount_path', value, { shouldDirty: true })}
                error={form.formState.errors.nas_mount_path?.message}
                success={!isDirty && successPath === currentNasPath && successPath !== null && successPath !== ''}
                placeholder="/media"
              />
            </div>

            <div className="flex items-start justify-between gap-4 rounded-lg border border-border bg-secondary/20 p-4">
              <div>
                <label htmlFor="prefer_existing_subs" className="text-sm font-medium text-foreground">
                  Prefer existing subtitles
                </label>
                <p className="text-xs text-muted-foreground mt-1">
                  When a video ships with a subtitle track (sidecar file or embedded)
                  that passes verification, use it as the source instead of
                  transcribing. You can override this per job on the submit sheet.
                </p>
              </div>
              <input
                id="prefer_existing_subs"
                type="checkbox"
                className="h-4 w-4 mt-1 shrink-0 accent-[var(--action-accent)]"
                checked={form.watch('prefer_existing_subs')}
                onChange={(e) =>
                  form.setValue('prefer_existing_subs', e.target.checked, { shouldDirty: true })}
              />
            </div>

            {/* Watch folders moved notice */}
            <div className="flex items-start gap-3 rounded-lg border border-border bg-secondary/20 p-4">
              <Sparkles className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" aria-hidden />
              <p className="text-xs text-muted-foreground">
                Watch folders and scheduled scans have moved to{' '}
                <Link
                  to="/automations"
                  className="font-medium text-primary hover:underline"
                >
                  Automations
                </Link>
                , where you can create watch-folder triggers, cron schedules, and webhooks.
              </p>
            </div>
          </div>
          <div className="px-6 py-4 bg-muted/30 border-t border-border flex justify-end">
            <button
              type="submit"
              disabled={mutation.isPending}
              className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:pointer-events-none disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
