export type SectionId =
  | 'media' | 'jellyfin' | 'ai-backends'
  | 'saved-configurations'

export type SectionGroup = 'STORAGE' | 'INTEGRATIONS' | 'AI'

export type SectionDef = Readonly<{
  id: SectionId
  label: string
  group: SectionGroup
  description: string
  /** Probe endpoint for the section's live-status dot; null → status
   *  stays 'idle' ("Not checked"), no request is ever made. */
  probe: { path: string; method: 'POST' | 'GET'; body?: unknown } | null
}>

export const SECTIONS: readonly SectionDef[] = [
  { id: 'media', label: 'Media Library', group: 'STORAGE',
    description: 'Where the worker reads videos and writes subtitle files inside the container.',
    probe: null },
  // jellyfin / ai-backends: auto-probe on visit via bodyless GET /health
  // endpoints that test the PERSISTED settings stored in the DB — no
  // request body needed. The explicit "Test Connection" handlers still
  // test the typed form values and override the pill via the status store.
  { id: 'jellyfin', label: 'Jellyfin', group: 'INTEGRATIONS',
    description: 'Media-server connection used to refresh libraries after a job.',
    probe: { path: '/api/v1/settings/jellyfin/health', method: 'GET' } },
  { id: 'ai-backends', label: 'AI Backends', group: 'AI',
    description: 'Transcription engine and translation provider configuration.',
    probe: { path: '/api/v1/settings/transcription/health', method: 'GET' } },
  { id: 'saved-configurations', label: 'Saved Configurations', group: 'AI',
    description: 'Reusable backend profiles selected when submitting a job.',
    probe: null },
] as const

export const DEFAULT_SECTION: SectionId = 'media'
export const isSectionId = (v: string | undefined): v is SectionId =>
  SECTIONS.some((s) => s.id === v)
