import type { Job } from '@/types/api'

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    status: 'queued',
    phase: null,
    progress: 0,
    file_path: '/media/Film.mkv',
    source_language: null,
    target_language: null,
    model_size: null,
    translation_provider: null,
    translation_model: null,
    log_path: null,
    error_message: null,
    source: 'manual',
    created_at: '2026-04-29T00:00:00Z',
    updated_at: '2026-04-29T00:00:00Z',
    completed_at: null,
    jellyfin_refreshed_at: null,
    verification_status: null,
    verification_score: null,
    verification_report: null,
    verified_at: null,
    ...overrides,
  }
}
