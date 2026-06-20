export const JOB_STATUS = {
  QUEUED: 'queued',
  PROCESSING: 'processing',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
} as const

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS]

export type VerificationStatus = 'running' | 'pass' | 'warn' | 'fail' | 'skipped' | 'error'

const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set([
  JOB_STATUS.QUEUED,
  JOB_STATUS.PROCESSING,
])

export function isActive(status: JobStatus): boolean {
  return ACTIVE_STATUSES.has(status)
}

export const JOB_PHASE = {
  EXTRACTING: 'extracting',
  TRANSCRIBING: 'transcribing',
  TRANSLATING: 'translating',
  WRITING: 'writing',
  DONE: 'done',
} as const

export type JobPhase = (typeof JOB_PHASE)[keyof typeof JOB_PHASE]

export type Job = {
  id: string
  status: JobStatus
  phase: JobPhase | null
  progress: number
  file_path: string
  source_language: string | null
  target_language: string | null
  model_size: string | null
  translation_provider: string | null
  translation_model: string | null
  log_path: string | null
  error_message: string | null
  source: string
  created_at: string
  updated_at: string
  completed_at: string | null
  jellyfin_refreshed_at: string | null
  verification_status: VerificationStatus | null
  verification_score: number | null
  verification_report: { summary: string; checks: Array<{ layer: string; name: string; severity: string; detail: string }> } | null
  verified_at: string | null
}

export type JobUpdatePayload = Pick<
  Job,
  'id' | 'status' | 'phase' | 'progress' | 'updated_at'
> & {
  // Failure events surface these so the SSE consumer can toast without an
  // extra fetch. Optional because non-failure updates omit them.
  file_path?: string | null
  error_message?: string | null
  // Verification fields — present on verification events, absent on others.
  verification_status?: VerificationStatus | null
  verification_score?: number | null
  verification_report?: { summary: string; checks: Array<{ layer: string; name: string; severity: string; detail: string }> } | null
  verified_at?: string | null
}

export type QueueStatePayload = {
  jobs: Job[]
  replayed_at: string
}

export type Settings = {
  id: number
  nas_mount_path: string
  jellyfin_url: string | null
  jellyfin_api_key: string | null
  transcription_api_url: string | null
  transcription_model: string | null
  transcription_api_key: string | null
  translation_provider: string | null
  translation_model: string | null
  translation_api_key: string | null
  translation_api_url: string | null
  hf_token: string | null
  watch_folders: string[] | null
  /** named snapshots of the AI-backend configuration. */
  profiles: BackendProfile[] | null
  created_at: string
  updated_at: string
}

export type BackendProfile = {
  name: string
  transcription_api_url?: string | null
  transcription_model?: string | null
  transcription_api_key?: string | null
  translation_provider?: string | null
  translation_model?: string | null
  translation_api_url?: string | null
  translation_api_key?: string | null
}

export type SubmitJobRequest = {
  file_path: string
  target_language: string
  model_size?: string
  translation_enabled?: boolean
  translation_provider?: string
  translation_model?: string
}

export type HealthResponse = {
  status: string
  db: string
  redis: string
}

export const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'] as const
export type TerminalStatus = (typeof TERMINAL_STATUSES)[number]

export type HistoryEntry = {
  id: string
  status: TerminalStatus
  file_path: string
  source_language: string | null
  target_language: string | null
  model_size: string | null
  translation_provider: string | null
  translation_model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  cost_usd: number | null
  srt_path: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  jellyfin_refreshed_at: string | null
  verification_status: VerificationStatus | null
  verification_score: number | null
}

export type HistoryDeleteResponse = {
  deleted: number
}

export type WatchFolderActivity = {
  auto_enqueued_count_24h: number
  recent_auto_jobs: HistoryEntry[]
  recent_skipped: { path: string; skipped_at: string }[]
  monitored_paths: string[]
}

export type FileBrowseEntry = {
  name: string
  size_bytes: number
  modified_at: string
  has_srt: boolean
}

export type FileBrowseResponse = {
  path: string
  parent: string | null
  directories: string[]
  files: FileBrowseEntry[]
}

// ── Automations ──────────────────────────────────────────────────────────────

export type TriggerType = 'watch' | 'cron' | 'webhook'

export type TriggerEventOutcome =
  | 'submitted'
  | 'skipped_no_rule'
  | 'skipped_existing_srt'
  | 'skipped_duplicate'
  | 'skipped_scan_limit'
  | 'failed_dispatch'

export type Action = Readonly<{
  profile_name: string
  source_language: string | null
  target_language: string | null
  skip_if_srt: boolean
}>

export type FileFilter = Readonly<{
  type: 'all' | 'subfolder' | 'name_contains'
  value: string | null
}>

export type Schedule = Readonly<{
  mode: 'hourly' | 'daily' | 'weekly' | 'monthly'
  every_n_hours?: number
  time?: string
  day_of_week?: number
  day_of_month?: number
}>

export type Trigger = Readonly<{
  id: string
  name: string
  type: TriggerType
  config: Record<string, unknown>
  action: Action | null
  file_filter: FileFilter | null
  enabled: boolean
  created_at: string
  updated_at: string
  last_fired_at: string | null
  fire_count_24h: number
}>

export type TriggerEvent = Readonly<{
  id: string
  trigger_id: string
  fired_at: string
  event_payload: Record<string, unknown>
  matched_rule_index: number | null
  outcome: TriggerEventOutcome
  job_id: string | null
  error_message: string | null
}>
