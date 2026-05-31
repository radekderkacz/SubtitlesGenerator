import { useState } from 'react'
import { AlertCircle, RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import RetryDialog from '@/components/RetryDialog/RetryDialog'
import { retryJob } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import { basename } from '@/lib/utils'
import type { Job, JobPhase } from '@/types/api'

const PHASE_LABEL: Record<JobPhase, string> = {
  extracting: 'Extracting Audio',
  transcribing: 'Transcribing',
  translating: 'Translating',
  writing: 'Writing SRT',
  done: 'Finalizing',
}

type Props = Readonly<{
  job: Job
}>

export default function ErrorCard({ job }: Props) {
  const [retryOpen, setRetryOpen] = useState(false)
  const filename = basename(job.file_path)
  const phaseLabel = job.phase ? PHASE_LABEL[job.phase] : 'Pre-pickup'

  const handleRetry = () =>
    withApiToast(() => retryJob(job.id), {
      successMessage: `Retrying ${filename}`,
    })

  return (
    <>
      <section
        aria-labelledby="error-card-heading"
        className="bg-card border rounded-lg p-6 space-y-4"
        style={{ borderColor: 'var(--phase-failed)' }}
      >
        <header className="flex items-start gap-3">
          <AlertCircle
            className="h-5 w-5 shrink-0 mt-0.5"
            style={{ color: 'var(--phase-failed)' }}
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <h3
              id="error-card-heading"
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: 'var(--phase-failed)' }}
            >
              Job failed during {phaseLabel}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              The pipeline stopped before producing an SRT. Review the message
              below and retry — the new run will use your current Settings.
            </p>
          </div>
        </header>
        <pre className="bg-background border border-border rounded p-3 font-mono text-xs text-foreground whitespace-pre-wrap break-words">
          {job.error_message ?? 'No error message recorded.'}
        </pre>
        <div className="flex items-center gap-2">
          <Button onClick={() => setRetryOpen(true)} className="gap-2">
            <RotateCw className="h-4 w-4" aria-hidden="true" />
            Retry
          </Button>
        </div>
      </section>
      <RetryDialog
        open={retryOpen}
        onOpenChange={setRetryOpen}
        filename={filename}
        onRetry={handleRetry}
      />
    </>
  )
}
