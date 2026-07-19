import type { Job } from '@/types/api'

/** Jobs freshly announced over SSE are stored as PARTIAL rows (see
 *  jobStore.applyJobUpdate) — every field outside the update payload,
 *  including `source`, is undefined until the next queue_state replay.
 *  All source inspection goes through here so no render path can crash
 *  on that window. */
export function isAutoRetryJob(job: Pick<Job, 'source'>): boolean {
  return (job.source ?? '').startsWith('auto-regen:')
}

/** The original job's ID embedded in an auto-retry clone's source tag. */
export function autoRetryOriginalId(job: Pick<Job, 'source'>): string {
  return (job.source ?? '').slice('auto-regen:'.length)
}
