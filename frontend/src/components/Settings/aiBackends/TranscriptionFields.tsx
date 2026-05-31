import type { UseFormReturn } from 'react-hook-form'
import { Cpu, Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import ConnectivityBadge from '@/components/ConnectivityBadge/ConnectivityBadge'
import type { ConnectivityStatus } from '@/components/ConnectivityBadge/ConnectivityBadge'
import type { FormValues } from './schema'

/**
 * Transcription Engine card — points the app at an OpenAI-compatible
 * /v1/audio/transcriptions endpoint (self-hosted Whisper server,
 * Groq, OpenAI, etc.). The app no longer ships a local-inference path.
 */
type Props = Readonly<{
  form: UseFormReturn<FormValues>
  handleTestTranscription: () => void
  isTestingTranscription: boolean
  transcriptionStatus: ConnectivityStatus
  transcriptionDetail: string
}>

export default function TranscriptionFields({
  form,
  handleTestTranscription,
  isTestingTranscription,
  transcriptionStatus,
  transcriptionDetail,
}: Props) {
  return (
    <div className="bg-card rounded-xl shadow-[0_20px_40px_rgba(0,0,0,0.4)] overflow-hidden">
      <div className="p-6 flex items-start gap-4">
        <div className="w-10 h-10 rounded-lg bg-secondary flex items-center justify-center text-primary shrink-0">
          <Cpu className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-foreground">Transcription Engine</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Point at an OpenAI-compatible <code className="font-mono">/v1/audio/transcriptions</code> endpoint
            (faster-whisper-server, speaches, Groq, OpenAI&hellip;).
          </p>
        </div>
      </div>
      <div className="px-6 pb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="flex flex-col gap-1.5 mb-6 max-w-sm md:col-span-2">
            <label htmlFor="transcription_preset" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Transcription Preset
            </label>
            <Select
              onValueChange={(v) => {
                if (v === 'groq') {
                  form.setValue('transcription_api_url', 'https://api.groq.com/openai/v1', { shouldDirty: true })
                  form.setValue('transcription_model', 'whisper-large-v3-turbo', { shouldDirty: true })
                } else if (v === 'openai') {
                  form.setValue('transcription_api_url', 'https://api.openai.com/v1', { shouldDirty: true })
                  form.setValue('transcription_model', 'whisper-1', { shouldDirty: true })
                }
                // 'custom' → leave fields as-is for manual entry
              }}
            >
              <SelectTrigger id="transcription_preset" className="w-full" aria-label="Transcription Preset">
                <SelectValue placeholder="Pick a hosted provider (or Custom)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="groq">Groq — fast, $0.04/h, ~100 MB cap</SelectItem>
                <SelectItem value="openai">OpenAI — 25 MB cap (short audio only)</SelectItem>
                <SelectItem value="custom">Custom (enter URL/model below)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground mt-1">
              Audio is compressed before upload. OpenAI&apos;s 25 MB limit means feature-length
              films need Groq or a self-hosted Whisper endpoint.
            </p>
          </div>
          <div className="flex flex-col gap-1.5 md:col-span-2">
            <label htmlFor="transcription_api_url" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              API URL
            </label>
            <Input
              id="transcription_api_url"
              type="url"
              placeholder="http://whisper.local:9000"
              className="font-mono"
              {...form.register('transcription_api_url')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="transcription_model" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Model
            </label>
            <Input
              id="transcription_model"
              type="text"
              placeholder="e.g. whisper-large-v3"
              className="font-mono"
              {...form.register('transcription_model')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="transcription_api_key" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              API Key (optional)
            </label>
            <Input
              id="transcription_api_key"
              type="password"
              placeholder="Leave blank for unauthenticated endpoints"
              className="font-mono"
              {...form.register('transcription_api_key')}
            />
          </div>
        </div>

        <div className="mt-6 pt-6 border-t border-border flex items-center gap-4">
          <button
            type="button"
            onClick={handleTestTranscription}
            disabled={isTestingTranscription}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary transition-colors disabled:pointer-events-none disabled:opacity-50"
          >
            {isTestingTranscription && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            Test Connection
          </button>
          <ConnectivityBadge status={transcriptionStatus} detail={transcriptionDetail} />
        </div>
      </div>
    </div>
  )
}
