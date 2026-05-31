import type { UseFormRegister } from 'react-hook-form'
import { RefreshCw } from 'lucide-react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { getModelGuidance, MODEL_STATUS_STYLES } from '@/lib/translation-models'
import ModelStatusBadge from './ModelStatusBadge'
import type { FormValues } from './schema'

type TranslationFieldsProps = Readonly<{
  provider: string
  register: UseFormRegister<FormValues>
  modelOptions: string[]
  isFetchingModels: boolean
  onRefreshModels: () => void
  modelValue: string
  onModelChange: (value: string) => void
}>

const MODEL_PLACEHOLDERS: Record<string, string> = {
  openai: 'gpt-4o',
  google: 'gemini-2.0-flash',
  openrouter: 'anthropic/claude-3.5-sonnet',
}

const API_KEY_PLACEHOLDERS: Record<string, string> = {
  openai: 'sk-…',
  openrouter: 'sk-or-v1-…',
  google: 'AIza…',
  custom: 'AIza…',
}

// Providers whose /v1/models endpoint we know how to query. Google's
// OpenAI-compat shim at /v1beta/openai/ DOES include a /models index —
// the earlier comment that claimed otherwise was wrong (fixed 2026-05-15).
// OpenRouter exposes the standard /api/v1/models at openrouter.ai (no
// URL configuration needed since the host is hard-coded server-side).
const PROVIDERS_WITH_MODEL_LIST = new Set([
  'ollama',
  'openai',
  'custom',
  'openrouter',
  'google',
])

export default function TranslationProviderFields({
  provider,
  register,
  modelOptions,
  isFetchingModels,
  onRefreshModels,
  modelValue,
  onModelChange,
}: TranslationFieldsProps) {
  if (provider === '') return null

  const urlField = (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="translation_api_url" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Base URL
      </label>
      <Input
        id="translation_api_url"
        type="url"
        placeholder={provider === 'custom' ? 'http://your-api-endpoint/v1' : 'http://ollama.local:11434'}
        className="font-mono"
        {...register('translation_api_url')}
      />
    </div>
  )

  const canRefresh = PROVIDERS_WITH_MODEL_LIST.has(provider)
  const useDropdown = canRefresh && modelOptions.length > 0
  const modelField = (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label htmlFor="translation_model" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Model
        </label>
        {canRefresh && (
          <button
            type="button"
            onClick={onRefreshModels}
            disabled={isFetchingModels}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 disabled:pointer-events-none"
            aria-label="Refresh available models"
          >
            <RefreshCw
              className={`h-3 w-3 ${isFetchingModels ? 'animate-spin' : ''}`}
              aria-hidden="true"
            />
            {isFetchingModels ? 'Fetching…' : 'Refresh models'}
          </button>
        )}
      </div>
      {useDropdown ? (
        <Select value={modelValue} onValueChange={(v) => onModelChange(v ?? '')}>
          <SelectTrigger id="translation_model" className="w-full font-mono">
            <SelectValue placeholder="Select a model" />
          </SelectTrigger>
          <SelectContent>
            {modelOptions.map((id) => {
              const guidance = getModelGuidance(id)
              return (
                <SelectItem key={id} value={id} className="font-mono">
                  <span className="flex items-center justify-between gap-3 w-full">
                    <span>{id}</span>
                    <ModelStatusBadge status={guidance.status} note={guidance.note} />
                  </span>
                </SelectItem>
              )
            })}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id="translation_model"
          type="text"
          placeholder={MODEL_PLACEHOLDERS[provider] ?? 'llama3'}
          className="font-mono"
          {...register('translation_model')}
        />
      )}
      {/* "Current selection" indicator beneath the input/dropdown. Same
          guidance map; shows the *note* in full (not just the short
          tag), since we have the room here and the note is the action-
          driving content. */}
      {modelValue && (
        <p className="text-xs text-muted-foreground flex items-start gap-2 mt-1">
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 rounded-full shrink-0 mt-1.5 ${MODEL_STATUS_STYLES[getModelGuidance(modelValue).status].dot}`}
          />
          <span>
            <strong className="text-foreground">
              {MODEL_STATUS_STYLES[getModelGuidance(modelValue).status].label}:{' '}
            </strong>
            {getModelGuidance(modelValue).note}
          </span>
        </p>
      )}
    </div>
  )

  // Provider-specific API-key prefix hint. Lookup table beats a nested
  // ternary (SonarQube S3358) and makes adding the next provider a
  // one-line change.
  const apiKeyPlaceholder =
    API_KEY_PLACEHOLDERS[provider] ?? 'AIza…'
  const apiKeyField = (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="translation_api_key" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        API Key
      </label>
      <Input
        id="translation_api_key"
        type="password"
        placeholder={apiKeyPlaceholder}
        className="font-mono"
        {...register('translation_api_key')}
      />
    </div>
  )

  if (provider === 'ollama') return <>{urlField}{modelField}</>
  // OpenRouter, OpenAI, and Google all use a fixed cloud endpoint server-
  // side; the user only supplies the API key + picks a model.
  if (provider === 'openai' || provider === 'google' || provider === 'openrouter')
    return <>{apiKeyField}{modelField}</>
  return <>{urlField}{modelField}{apiKeyField}</>
}
