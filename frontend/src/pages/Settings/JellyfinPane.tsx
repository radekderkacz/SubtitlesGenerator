import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { apiFetch, ApiRequestError } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import { Input } from '@/components/ui/input'
import SectionHeader from '@/components/Settings/SectionHeader'
import { useSectionStatus } from '@/hooks/useSectionStatus'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'
import type { Settings } from '@/types/api'

const schema = z.object({
  jellyfin_url: z.string(),
  jellyfin_api_key: z.string(),
})

type FormValues = z.infer<typeof schema>

type Props = Readonly<{
  onDirtyChange: (isDirty: boolean) => void
}>

export default function JellyfinPane({ onDirtyChange }: Props) {
  const st = useSectionStatus('jellyfin')
  const [isTesting, setIsTesting] = useState(false)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      jellyfin_url: '',
      jellyfin_api_key: '',
    },
  })

  useEffect(() => {
    if (settings) {
      form.reset({
        jellyfin_url: settings.jellyfin_url ?? '',
        jellyfin_api_key: settings.jellyfin_api_key ?? '',
      })
    }
  }, [settings, form])

  const isDirty = form.formState.isDirty
  useEffect(() => {
    onDirtyChange(isDirty)
    // Clear this section's dirty flag on unmount (navigation away) so the
    // sticky unsaved-changes bar can't lie about an unmounted section.
    return () => onDirtyChange(false)
  }, [isDirty, onDirtyChange])

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
    },
    onError: (error) => {
      if (error instanceof ApiRequestError) {
        toast.error(`Failed to save settings: ${error.message}`)
      } else {
        toast.error('Failed to save settings')
      }
    },
  })

  async function handleTestConnection() {
    setIsTesting(true)
    // "Test Connection" tests the values currently in the form (possibly
    // unsaved) — its result must drive the SectionHeader pill. We set the
    // shared status store from THIS response, not a separate st.check()
    // bodyless probe (which tests persisted DB settings, not what the user
    // typed). The on-visit lazy probe in useSectionStatus already seeds the
    // dot from persisted settings before any Test click.
    try {
      const r = await apiFetch<{ ok: boolean; detail: string }>(
        '/api/v1/settings/test-jellyfin',
        {
          method: 'POST',
          body: JSON.stringify({
            url: form.getValues('jellyfin_url'),
            api_key: form.getValues('jellyfin_api_key'),
          }),
        }
      )
      useSettingsStatusStore.getState().set('jellyfin', {
        status: r.ok ? 'ok' : 'warn',
        detail: r.detail ?? null,
      })
    } catch (e) {
      useSettingsStatusStore.getState().set('jellyfin', {
        status: 'error',
        detail: e instanceof Error ? e.message : 'Unreachable',
      })
    } finally {
      setIsTesting(false)
    }
  }

  function onSubmit(data: FormValues) {
    mutation.mutate(data)
  }

  useEffect(() => {
    const onSave = (e: Event) => {
      if ((e as CustomEvent).detail === 'jellyfin') {
        form.handleSubmit(onSubmit)().catch(() => {})
      }
    }
    globalThis.addEventListener('settings:save', onSave)
    return () => globalThis.removeEventListener('settings:save', onSave)
  }, [form, onSubmit])

  return (
    <div data-testid="pane-jellyfin">
      <SectionHeader
        title="Jellyfin"
        description="Media-server connection used to refresh libraries after a job."
        status={st.status}
        detail={st.detail}
        action={
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={isTesting}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary transition-colors disabled:pointer-events-none disabled:opacity-50"
          >
            {isTesting && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            Test Connection
          </button>
        }
      />
      <form onSubmit={form.handleSubmit(onSubmit)} className="max-w-2xl">
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="p-6 border-b border-border">
            <h2 className="text-base font-semibold text-foreground">Jellyfin Integration</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Connect to your Jellyfin media server for automatic library refresh
            </p>
          </div>
          <div className="p-6 flex flex-col gap-6">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="jellyfin_url" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Server URL
              </label>
              <Input
                id="jellyfin_url"
                type="url"
                placeholder="http://jellyfin.local:8096"
                className="font-mono"
                {...form.register('jellyfin_url')}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="jellyfin_api_key" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                API Key
              </label>
              <Input
                id="jellyfin_api_key"
                type="password"
                placeholder="Enter API key"
                className="font-mono"
                {...form.register('jellyfin_api_key')}
              />
              <p className="text-xs text-muted-foreground">
                Generate this in Jellyfin Dashboard › Advanced › API Keys
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
