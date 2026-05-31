import { useEffect, useState } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Languages, Loader2 } from 'lucide-react'
import { apiFetch, ApiRequestError } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import ConnectivityBadge from '@/components/ConnectivityBadge/ConnectivityBadge'
import type { ConnectivityStatus } from '@/components/ConnectivityBadge/ConnectivityBadge'
import TestModelButton from '@/components/Settings/TestModelButton'
import SectionHeader from '@/components/Settings/SectionHeader'
import ModelGuidanceHelp from '@/components/Settings/aiBackends/ModelGuidanceHelp'
import TranslationProviderFields from '@/components/Settings/aiBackends/TranslationProviderFields'
import TranscriptionFields from '@/components/Settings/aiBackends/TranscriptionFields'
import { schema, type FormValues } from '@/components/Settings/aiBackends/schema'
import { useSectionStatus } from '@/hooks/useSectionStatus'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'
import type { Settings } from '@/types/api'

type Props = Readonly<{
  onDirtyChange: (isDirty: boolean) => void
}>

export default function AiBackendsPane({ onDirtyChange }: Props) {
  const st = useSectionStatus('ai-backends')
  const [transcriptionStatus, setTranscriptionStatus] = useState<ConnectivityStatus>('idle')
  const [transcriptionDetail, setTranscriptionDetail] = useState('')
  const [isTestingTranscription, setIsTestingTranscription] = useState(false)
  const [translationStatus, setTranslationStatus] = useState<ConnectivityStatus>('idle')
  const [translationDetail, setTranslationDetail] = useState('')
  const [isTestingTranslation, setIsTestingTranslation] = useState(false)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      transcription_api_url: settings?.transcription_api_url ?? '',
      transcription_model: settings?.transcription_model ?? '',
      transcription_api_key: settings?.transcription_api_key ?? '',
      translation_provider: settings?.translation_provider ?? '',
      translation_model: settings?.translation_model ?? '',
      translation_api_key: settings?.translation_api_key ?? '',
      translation_api_url: settings?.translation_api_url ?? '',
    },
  })

  useEffect(() => {
    if (settings && !form.formState.isDirty) {
      form.reset({
        transcription_api_url: settings.transcription_api_url ?? '',
        transcription_model: settings.transcription_model ?? '',
        transcription_api_key: settings.transcription_api_key ?? '',
        translation_provider: settings.translation_provider ?? '',
        translation_model: settings.translation_model ?? '',
        translation_api_key: settings.translation_api_key ?? '',
        translation_api_url: settings.translation_api_url ?? '',
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

  const [transcriptionApiUrl, transcriptionModel, transcriptionApiKey] =
    form.watch(['transcription_api_url', 'transcription_model', 'transcription_api_key'])
  useEffect(() => {
    setTranscriptionStatus('idle')
    setTranscriptionDetail('')
  }, [transcriptionApiUrl, transcriptionModel, transcriptionApiKey])

  const [translationProvider, translationModel, translationApiKey, translationApiUrl] =
    form.watch(['translation_provider', 'translation_model', 'translation_api_key', 'translation_api_url'])
  useEffect(() => {
    setTranslationStatus('idle')
    setTranslationDetail('')
  }, [translationProvider, translationModel, translationApiKey, translationApiUrl])

  const [translationModelOptions, setTranslationModelOptions] = useState<string[]>([])
  const [isFetchingTranslationModels, setIsFetchingTranslationModels] = useState(false)
  // Drop the cached list whenever connection inputs change — the previous
  // list belonged to a different endpoint, so the user must refetch.
  useEffect(() => {
    setTranslationModelOptions([])
  }, [translationProvider, translationApiUrl, translationApiKey])

  async function handleRefreshTranslationModels() {
    setIsFetchingTranslationModels(true)
    try {
      const apiKey = form.getValues('translation_api_key')
      const result = await apiFetch<{ models: string[]; detail: string | null }>(
        '/api/v1/settings/list-translation-models',
        {
          method: 'POST',
          body: JSON.stringify({
            provider: form.getValues('translation_provider'),
            url: form.getValues('translation_api_url') || undefined,
            // Send the "***" sentinel through (don't strip it) so the
            // backend un-masks the stored key from the DB, like Jellyfin.
            api_key: apiKey || undefined,
          }),
        },
      )
      setTranslationModelOptions(result.models)
      if (result.models.length === 0) {
        toast.error(result.detail ?? 'No models found at that endpoint')
      } else {
        toast(`Loaded ${result.models.length} model${result.models.length === 1 ? '' : 's'}`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch models'
      toast.error(message)
    } finally {
      setIsFetchingTranslationModels(false)
    }
  }

  const mutation = useMutation({
    mutationFn: (data: FormValues) => {
      const payload = {
        ...data,
        transcription_api_url: data.transcription_api_url || null,
        transcription_model: data.transcription_model || null,
        // Empty translation fields → null so the backend treats them as unset.
        translation_provider: data.translation_provider || null,
        translation_model: data.translation_model || null,
        translation_api_url: data.translation_api_url || null,
      }
      return apiFetch<{ status: string }>('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
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

  async function handleTestTranscription() {
    setTranscriptionStatus('testing')
    setTranscriptionDetail('')
    setIsTestingTranscription(true)
    try {
      const apiKey = form.getValues('transcription_api_key')
      const result = await apiFetch<{ ok: boolean; detail: string }>(
        '/api/v1/settings/test-transcription',
        {
          method: 'POST',
          body: JSON.stringify({
            url: form.getValues('transcription_api_url') || undefined,
            model: form.getValues('transcription_model') || undefined,
            // Send the "***" sentinel through (don't strip it) so the
            // backend un-masks the stored key from the DB, like Jellyfin.
            api_key: apiKey || undefined,
          }),
        }
      )
      setTranscriptionStatus(result.ok ? 'ok' : 'failed')
      setTranscriptionDetail(result.detail)
      // Drive the rail dot / SectionHeader pill from THIS form-values
      // test result. ai-backends has no auto-probe (sections.ts probe:
      // null — the endpoint needs a body), so the explicit Test is the
      // only thing that can populate the shared status store.
      useSettingsStatusStore.getState().set('ai-backends', {
        status: result.ok ? 'ok' : 'warn',
        detail: result.detail ?? null,
      })
    } catch (error) {
      setTranscriptionStatus('failed')
      setTranscriptionDetail(error instanceof Error ? error.message : 'Unknown error')
      useSettingsStatusStore.getState().set('ai-backends', {
        status: 'error',
        detail: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setIsTestingTranscription(false)
    }
  }

  async function handleTestTranslation() {
    setTranslationStatus('testing')
    setTranslationDetail('')
    setIsTestingTranslation(true)
    try {
      const apiKey = form.getValues('translation_api_key')
      const result = await apiFetch<{ ok: boolean; detail: string }>(
        '/api/v1/settings/test-translation',
        {
          method: 'POST',
          body: JSON.stringify({
            provider: form.getValues('translation_provider'),
            url: form.getValues('translation_api_url') || undefined,
            model: form.getValues('translation_model') || undefined,
            // Send the "***" sentinel through (don't strip it) so the
            // backend un-masks the stored key from the DB, like Jellyfin.
            api_key: apiKey || undefined,
          }),
        }
      )
      setTranslationStatus(result.ok ? 'ok' : 'failed')
      setTranslationDetail(result.detail)
    } catch (error) {
      setTranslationStatus('failed')
      setTranslationDetail(error instanceof Error ? error.message : 'Unknown error')
    } finally {
      setIsTestingTranslation(false)
    }
  }

  function onSubmit(data: FormValues) {
    mutation.mutate(data)
  }

  useEffect(() => {
    const onSave = (e: Event) => {
      if ((e as CustomEvent).detail === 'ai-backends') {
        form.handleSubmit(onSubmit)().catch(() => {})
      }
    }
    globalThis.addEventListener('settings:save', onSave)
    return () => globalThis.removeEventListener('settings:save', onSave)
  }, [form, onSubmit])

  return (
    <div data-testid="pane-ai-backends">
      <SectionHeader
        title="AI Backends"
        description="Transcription engine and translation provider configuration."
        status={st.status}
        detail={st.detail}
      />
      <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-6 max-w-[900px]">
        <TranscriptionFields
          form={form}
          handleTestTranscription={handleTestTranscription}
          isTestingTranscription={isTestingTranscription}
          transcriptionStatus={transcriptionStatus}
          transcriptionDetail={transcriptionDetail}
        />

        <div className="bg-card rounded-xl shadow-[0_20px_40px_rgba(0,0,0,0.4)] overflow-hidden">
          <div className="p-6 flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-secondary flex items-center justify-center text-primary shrink-0">
              <Languages className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold text-foreground">Translation Engine</h2>
              <p className="text-xs text-muted-foreground mt-1">
                Local or remote LLM settings for translating extracted subtitles. Optional —
                omit to generate transcription-only subtitles.
              </p>
            </div>
          </div>
          <div className="px-6 pb-6">
            <div className="flex flex-col gap-4">
              <ModelGuidanceHelp />
              <div className="flex flex-col gap-1.5">
                <label htmlFor="translation_provider" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Provider
                </label>
                <Controller
                  control={form.control}
                  name="translation_provider"
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={(v) => {
                        // Switching provider must reset the model field —
                        // a model id is provider-specific (gemma3 for
                        // Ollama, gemini-2.0-flash for Google, anthropic/
                        // claude-3.5-sonnet for OpenRouter, etc.). Leaving
                        // the old value silently sends the wrong id to the
                        // new provider and the test/save fails confusingly
                        // (bug reported 2026-05-15: picking Google still
                        // showed gemma3 in the model field).
                        field.onChange(v ?? '')
                        form.setValue('translation_model', '', { shouldDirty: true })
                        // Also clear the cached dropdown options from the
                        // OLD provider so we don't show stale models.
                        setTranslationModelOptions([])
                      }}
                    >
                      <SelectTrigger id="translation_provider" className="w-full max-w-xs">
                        <SelectValue placeholder="None (transcription only)" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="">None (transcription only)</SelectItem>
                        <SelectItem value="ollama">Ollama (local)</SelectItem>
                        <SelectItem value="openai">OpenAI API</SelectItem>
                        <SelectItem value="google">Google AI</SelectItem>
                        <SelectItem value="openrouter">OpenRouter (multi-provider gateway)</SelectItem>
                        <SelectItem value="custom">Custom (OpenAI-compatible)</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              {translationProvider !== '' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <TranslationProviderFields
                    provider={translationProvider}
                    register={form.register}
                    modelOptions={translationModelOptions}
                    isFetchingModels={isFetchingTranslationModels}
                    onRefreshModels={handleRefreshTranslationModels}
                    modelValue={translationModel}
                    onModelChange={(v) => form.setValue('translation_model', v, { shouldDirty: true })}
                  />
                </div>
              )}
            </div>
            <div className="mt-6 pt-6 border-t border-border flex flex-col gap-4">
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={handleTestTranslation}
                  disabled={translationProvider === '' || isTestingTranslation}
                  className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary transition-colors disabled:pointer-events-none disabled:opacity-50"
                >
                  {isTestingTranslation && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  Test Connection
                </button>
                <ConnectivityBadge status={translationStatus} detail={translationDetail} />
              </div>
              {/* Deeper probe than the connectivity ping — runs an actual
                  translation + glossary extraction and reports proper-noun
                  preservation + JSON-format compliance + sec/cue. Catches
                  the failure modes that bit the user on 2026-05-15 within
                  ~30s. */}
              <TestModelButton
                provider={translationProvider}
                url={translationApiUrl ?? ''}
                model={translationModel ?? ''}
                apiKey={translationApiKey ?? ''}
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:pointer-events-none disabled:opacity-50"
          >
            {mutation.isPending ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </form>
    </div>
  )
}
