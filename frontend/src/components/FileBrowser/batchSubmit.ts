import { submitJob } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import { buildJobPayload } from '@/components/SubmitSheet/GenerationControls'
import type { GenerationControlsValues } from '@/components/SubmitSheet/GenerationControls'

/** Submit one job per path; single summary toast; returns succeeded count. */
export async function submitBatch(
  eligiblePaths: ReadonlyArray<string>,
  values: GenerationControlsValues,
): Promise<number> {
  let succeeded = 0
  let failed = 0
  for (const fullPath of eligiblePaths) {
    // Pass no successMessage so withApiToast stays silent on success — we
    // emit a single summary toast at the end. Per-file errors still surface.
    const ok = await withApiToast(() => submitJob(buildJobPayload(fullPath, values)))
    if (ok) succeeded += 1
    else failed += 1
  }
  if (succeeded > 0 || failed === 0) {
    const tail = failed > 0 ? ` (${failed} failed)` : ''
    // Deferred import: keeps sonner out of this module's import graph
    // until the rare batch-summary path actually runs.
    const { toast } = await import('sonner')
    toast(`Queued ${succeeded} job${succeeded === 1 ? '' : 's'}${tail}`)
  }
  return succeeded
}
