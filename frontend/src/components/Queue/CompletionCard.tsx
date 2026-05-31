import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, CheckCircle2, Copy, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { ApiRequestError, apiFetch, refreshJellyfin } from '@/lib/api'
import { useJobStore } from '@/store/jobStore'
import { basename, dirname, formatDuration } from '@/lib/utils'
import type { Job, Settings } from '@/types/api'

type Props = Readonly<{
  job: Job
}>

function srtPathFor(job: Job): string | null {
  if (!job.target_language) return null
  const dir = dirname(job.file_path)
  const base = basename(job.file_path).replace(/\.[^.]+$/, '')
  return `${dir}${base}.${job.target_language}.srt`
}

function durationSeconds(job: Job): number | null {
  if (!job.completed_at) return null
  const start = Date.parse(job.created_at)
  const end = Date.parse(job.completed_at)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return Math.max(0, (end - start) / 1000)
}

export default function CompletionCard({ job }: Props) {
  const srtPath = srtPathFor(job)
  const seconds = durationSeconds(job)
  const [copied, setCopied] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const applyJobUpdate = useJobStore((s) => s.applyJobUpdate)

  // Settings drives whether the Jellyfin section is shown at all (AC: omit
  // entirely when not configured). Cheap query; cached at 'settings' key
  // alongside the rest of the app.
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })
  const jellyfinConfigured = Boolean(settings?.jellyfin_url && settings.jellyfin_api_key)

  const handleCopy = async () => {
    if (srtPath === null) return
    try {
      await navigator.clipboard.writeText(srtPath)
      setCopied(true)
      globalThis.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard write can fail if the page is unfocused; silently swallow.
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const updated = await refreshJellyfin(job.id)
      // Push the updated row into the store so other consumers see the new
      // jellyfin_refreshed_at without waiting for an SSE round-trip.
      applyJobUpdate(updated)
      toast.success('Jellyfin library refresh triggered')
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : 'Refresh failed'
      toast.error(message)
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <section
      aria-labelledby="completion-card-heading"
      className="bg-card border border-border rounded-lg overflow-hidden"
    >
      <div className="p-6 space-y-4">
        <h3
          id="completion-card-heading"
          className="text-sm font-semibold text-muted-foreground uppercase tracking-wider"
        >
          Output File
        </h3>
        {srtPath === null ? (
          <p className="text-xs text-muted-foreground">
            SRT path unavailable (target language not recorded).
          </p>
        ) : (
          <div className="bg-background border border-border rounded p-3 flex items-center justify-between gap-3">
            <span className="font-mono text-xs text-foreground truncate flex-1" title={srtPath}>
              {srtPath}
            </span>
            <button
              type="button"
              onClick={handleCopy}
              aria-label="Copy SRT path"
              className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Detected language</dt>
          <dd className="font-mono text-foreground">{job.source_language ?? '—'}</dd>
          <dt className="text-muted-foreground">Target language</dt>
          <dd className="font-mono text-foreground">{job.target_language ?? '—'}</dd>
          <dt className="text-muted-foreground">Duration</dt>
          <dd className="font-mono text-foreground">
            {seconds === null ? '—' : formatDuration(seconds)}
          </dd>
          <dt className="text-muted-foreground">Model</dt>
          <dd className="font-mono text-foreground">{job.model_size ?? 'system default'}</dd>
        </dl>
        {jellyfinConfigured && (
          <div
            className="flex items-center justify-between gap-3 text-xs border-t border-border pt-3"
            aria-label="Jellyfin status"
          >
            {job.jellyfin_refreshed_at ? (
              <span
                className="flex items-center gap-2 font-medium"
                style={{ color: 'var(--phase-done)' }}
              >
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                Library refreshed ✓
              </span>
            ) : (
              <>
                <span className="flex items-center gap-2 text-muted-foreground">
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  Refresh pending
                </span>
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={refreshing}
                  className="text-primary hover:underline flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {refreshing && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
                  <span>Refresh Now</span>
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {jellyfinConfigured && settings?.jellyfin_url && (
        <a
          href={settings.jellyfin_url}
          target="_blank"
          rel="noreferrer"
          className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground border-t border-border py-3 text-sm font-bold transition-colors"
        >
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
          <span>Open in Jellyfin</span>
        </a>
      )}
    </section>
  )
}
