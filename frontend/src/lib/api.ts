import type { Schedule, Trigger, TriggerEvent, TriggerEventOutcome } from '@/types/api'

type ApiError = {
  // FastAPI returns `detail` as a string for HTTPException but as an
  // array of `{loc, msg, type}` for 422 validation errors — the raw
  // value is genuinely `unknown` and MUST be coerced before it reaches
  // an Error message or the UI (else it stringifies to "[object Object]").
  detail: unknown
  code: string
}

export class ApiRequestError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

/**
 * Coerce a FastAPI `detail` (string | 422-array | object | anything)
 * into a human-readable string. The durable guard: every
 * ApiRequestError message is a real string, so nothing downstream can
 * render "[object Object]". Never JSON.stringify the raw payload — it
 * leaks internal field paths and reads worse than a generic fallback.
 */
export function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim() !== '') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) =>
        d && typeof d === 'object' && typeof (d as { msg?: unknown }).msg === 'string'
          ? (d as { msg: string }).msg
          : null,
      )
      .filter((m): m is string => m !== null)
    if (msgs.length > 0) return msgs.join('; ')
  }
  if (detail && typeof detail === 'object') {
    const o = detail as { message?: unknown; msg?: unknown }
    if (typeof o.message === 'string') return o.message
    if (typeof o.msg === 'string') return o.msg
  }
  return fallback
}

/**
 * Typed fetch wrapper for all API calls.
 * For POST/PUT/PATCH with JSON body, callers must pass `body: JSON.stringify(data)`
 * and ensure `Content-Type: application/json` is in headers (set by default).
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!response.ok) {
    let error: ApiError = { detail: response.statusText, code: 'UNKNOWN_ERROR' }
    try {
      error = (await response.json()) as ApiError
    } catch {
      // keep default
    }
    throw new ApiRequestError(response.status, error.code, detailToMessage(error.detail, response.statusText))
  }

  return response.json() as Promise<T>
}

/**
 * DELETE /api/v1/jobs/{id} — semantics depend on backend job status:
 * processing → cancel (status=cancelled, event published); queued/terminal → hard-delete.
 * Returns void; the SSE stream brings the resulting state into the store.
 */
export async function cancelOrRemoveJob(id: string): Promise<void> {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    let error: ApiError = { detail: response.statusText, code: 'UNKNOWN_ERROR' }
    try {
      error = (await response.json()) as ApiError
    } catch {
      // keep default
    }
    throw new ApiRequestError(response.status, error.code, detailToMessage(error.detail, response.statusText))
  }
}

/**
 * POST /api/v1/jobs/stop-all — cancel every queued+processing job.
 */
export async function stopAllJobs(): Promise<void> {
  await apiFetch<unknown[]>('/api/v1/jobs/stop-all', { method: 'POST' })
}

/**
 * POST /api/v1/jobs — submit a new transcription job.
 * SP-2: replaced language/model/translation_provider/translation_model with
 * source_language + translate + target_language + profile_name.
 */
export type JobSubmitPayload = {
  file_path: string
  profile_name: string
  source_language: string
  translate: boolean
  target_language?: string
  /** Omitted = follow the global "prefer existing subtitles" setting. */
  use_existing_subs?: boolean
}

export type JobSubmitResponse = {
  id: string
  status: string
  created_at: string
}

export async function submitJob(payload: JobSubmitPayload): Promise<JobSubmitResponse> {
  return apiFetch<JobSubmitResponse>('/api/v1/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * GET /api/v1/files/browse?path=<optional> — list a NAS directory.
 * Path defaults to settings.nas_mount_path on the backend when absent.
 */
export async function browseDirectory(path?: string): Promise<import('@/types/api').FileBrowseResponse> {
  const qs = path === undefined ? '' : `?path=${encodeURIComponent(path)}`
  return apiFetch<import('@/types/api').FileBrowseResponse>(`/api/v1/files/browse${qs}`)
}

/**
 * GET /api/v1/watch-folders/activity dashboard panel data.
 */
export async function getWatchFolderActivity(): Promise<import('@/types/api').WatchFolderActivity> {
  return apiFetch<import('@/types/api').WatchFolderActivity>(
    '/api/v1/watch-folders/activity',
  )
}

/**
 * GET /api/v1/jobs/:id — fetch a single job by id; 404 → ApiRequestError.
 */
export async function getJob(id: string): Promise<import('@/types/api').Job> {
  return apiFetch<import('@/types/api').Job>(`/api/v1/jobs/${encodeURIComponent(id)}`)
}

/**
 * GET /api/v1/history/:id/log — return the raw log file as plain text.
 * 404 (LOG_NOT_FOUND) propagates as ApiRequestError so the caller can fall
 * back to a "no log available" treatment.
 */
export async function getJobLog(id: string): Promise<string> {
  const response = await fetch(`/api/v1/history/${encodeURIComponent(id)}/log`)
  if (!response.ok) {
    let error: ApiError = { detail: response.statusText, code: 'UNKNOWN_ERROR' }
    try {
      error = (await response.json()) as ApiError
    } catch {
      // not JSON — keep default
    }
    throw new ApiRequestError(response.status, error.code, detailToMessage(error.detail, response.statusText))
  }
  return response.text()
}

/**
 * POST /api/v1/jobs/:id/jellyfin-refresh — manually trigger a Jellyfin library
 * scan for a completed job. Backend returns the updated Job (with the new
 * `jellyfin_refreshed_at` timestamp) on success or a typed ApiRequestError on
 * failure (404 / 409 / 422 / 502).
 */
export async function refreshJellyfin(id: string): Promise<import('@/types/api').Job> {
  return apiFetch<import('@/types/api').Job>(
    `/api/v1/jobs/${encodeURIComponent(id)}/jellyfin-refresh`,
    { method: 'POST' },
  )
}

/**
 * URL of the per-job log endpoint, suitable for an `<a href>` download
 * (the browser fetches it directly and saves the body as the file content).
 */
export function downloadJobLogUrl(id: string): string {
  return `/api/v1/history/${encodeURIComponent(id)}/log`
}

/**
 * GET /api/v1/history — terminal jobs (completed/failed/cancelled), DESC.
 * Optional `status` filter must be one of the terminal statuses; backend
 * rejects anything else with 422.
 */
export async function listHistory(
  status?: import('@/types/api').TerminalStatus,
): Promise<import('@/types/api').HistoryEntry[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiFetch<import('@/types/api').HistoryEntry[]>(`/api/v1/history${qs}`)
}

/**
 * DELETE /api/v1/history — purge every terminal job. Active and queued jobs
 * are preserved.
 */
export async function deleteHistory(): Promise<import('@/types/api').HistoryDeleteResponse> {
  return apiFetch<import('@/types/api').HistoryDeleteResponse>('/api/v1/history', {
    method: 'DELETE',
  })
}

/**
 * POST /api/v1/jobs/{id}/retry — re-enqueue a failed job using the current
 * Settings configuration. Per-retry model overrides are no longer accepted
 * The new job inherits whatever is in Settings now.
 */
export async function retryJob(id: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(id)}/retry`, {
    method: 'POST',
  })
}

export type TestTranslationModelPayload = Readonly<{
  provider: string
  url?: string
  model: string
  api_key?: string
  target_language?: string
}>

export type TestTranslationModelResponse = Readonly<{
  ok: boolean
  preserves_proper_nouns: boolean | null
  glossary_json_valid: boolean | null
  sec_per_segment: number | null
  sample_translation: string | null
  sample_glossary: string[] | null
  detail: string
}>

/**
 * POST /api/v1/settings/test-translation-model — runs two probes against
 * a candidate (provider, model) and reports proper-noun preservation +
 * glossary JSON-format compliance + per-cue latency. Used by the
 * Settings → AI Backends "Test this model" button so a user can validate
 * a model in ~30 seconds rather than discovering its limits 90 min into
 * a real subtitle run.
 */
export async function testTranslationModel(
  payload: TestTranslationModelPayload,
): Promise<TestTranslationModelResponse> {
  return apiFetch<TestTranslationModelResponse>(
    '/api/v1/settings/test-translation-model',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

/** POST /api/v1/jobs/:id/verify — re-run subtitle verification. */
export async function reverifyJob(id: string): Promise<void> {
  await apiFetch(`/api/v1/jobs/${encodeURIComponent(id)}/verify`, { method: 'POST' })
}

/** POST /api/v1/jobs/:id/regenerate — re-queue a finished job's file with its original settings. */
export async function regenerateJob(id: string): Promise<void> {
  await apiFetch(`/api/v1/jobs/${encodeURIComponent(id)}/regenerate`, { method: 'POST' })
}

// ── Automations API ──────────────────────────────────────────────────────────

export const listTriggers = (): Promise<Trigger[]> =>
  apiFetch<Trigger[]>('/api/v1/triggers')

export const getTrigger = (id: string): Promise<Trigger> =>
  apiFetch<Trigger>(`/api/v1/triggers/${encodeURIComponent(id)}`)

export const createTrigger = (
  body: Omit<Trigger, 'id' | 'created_at' | 'updated_at' | 'last_fired_at' | 'fire_count_24h'>,
): Promise<Trigger> =>
  apiFetch<Trigger>('/api/v1/triggers', { method: 'POST', body: JSON.stringify(body) })

export const updateTrigger = (
  id: string,
  body: Partial<Pick<Trigger, 'name' | 'config' | 'action' | 'file_filter' | 'enabled'>>,
): Promise<Trigger> =>
  apiFetch<Trigger>(`/api/v1/triggers/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })

export const previewCron = (
  schedule: Schedule,
  count = 3,
): Promise<{ next_fires: string[] }> =>
  apiFetch<{ next_fires: string[] }>('/api/v1/triggers/cron/preview', {
    method: 'POST',
    body: JSON.stringify({ schedule, count }),
  })

export const deleteTrigger = (id: string): Promise<void> =>
  apiFetch<void>(`/api/v1/triggers/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const fireTrigger = (id: string): Promise<{ fired: number }> =>
  apiFetch<{ fired: number }>(
    `/api/v1/triggers/${encodeURIComponent(id)}/fire`,
    { method: 'POST' },
  )

export const revealTriggerSecret = (id: string): Promise<{ webhook_secret: string }> =>
  apiFetch<{ webhook_secret: string }>(
    `/api/v1/triggers/${encodeURIComponent(id)}/secret`,
  )

export const listTriggerEvents = (
  opts: { outcome?: TriggerEventOutcome; limit?: number } = {},
): Promise<TriggerEvent[]> => {
  const qs = new URLSearchParams()
  if (opts.outcome) qs.set('outcome', opts.outcome)
  qs.set('limit', String(opts.limit ?? 100))
  return apiFetch<TriggerEvent[]>(`/api/v1/triggers/events?${qs.toString()}`)
}
