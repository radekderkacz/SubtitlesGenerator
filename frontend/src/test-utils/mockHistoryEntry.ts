import type { HistoryEntry } from '@/types/api'

/**
 * Factory for a fully-populated `HistoryEntry` test fixture. Mirrors
 * `makeJob` — every required field has a sane default so a widening of
 * `HistoryEntry` (e.g. the SP-3 usage/cost columns) only needs the
 * default added here, not at every call site. Use this for any mock that
 * feeds a `HistoryEntry[]` (e.g. `WatchFolderActivity.recent_auto_jobs`)
 * instead of spreading a `Job`, which structurally drifts as the two
 * types diverge.
 */
export function makeHistoryEntry(
  overrides: Partial<HistoryEntry> = {},
): HistoryEntry {
  return {
    id: 'h1',
    status: 'completed',
    file_path: '/media/Film.mkv',
    source_language: null,
    target_language: null,
    model_size: null,
    translation_provider: null,
    translation_model: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    cost_usd: null,
    srt_path: null,
    error_message: null,
    created_at: '2026-04-29T00:00:00Z',
    updated_at: '2026-04-29T00:00:00Z',
    completed_at: '2026-04-29T00:00:00Z',
    jellyfin_refreshed_at: null,
    ...overrides,
  }
}
