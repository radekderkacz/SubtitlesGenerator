import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Toaster } from '@/components/ui/sonner'
import JobRow from './JobRow'
import { makeJob } from '@/test-utils/mockJob'

vi.mock('@/lib/api', () => ({
  cancelOrRemoveJob: vi.fn(),
  retryJob: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.name = 'ApiRequestError'
      this.status = status
      this.code = code
    }
  },
}))

function getRowButton() {
  // The row is a <div role="button"> with aria-pressed; nested cancel button has
  // an explicit aria-label. Filter to the row by aria-pressed presence.
  return screen
    .getAllByRole('button')
    .find((b) => b.hasAttribute('aria-pressed')) as HTMLElement
}

describe('JobRow', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:05:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the filename and the dirname underneath', () => {
    render(
      <JobRow
        job={makeJob({ file_path: '/media/films/foreign/The.Grand.Illusion.1937.mkv' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('The.Grand.Illusion.1937.mkv')).toBeInTheDocument()
    expect(screen.getByText('/media/films/foreign/')).toBeInTheDocument()
  })

  it('exposes the full path via title attribute for hover', () => {
    render(
      <JobRow
        job={makeJob({ file_path: '/media/films/foreign/The.Grand.Illusion.1937.mkv' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    const filenameSpan = screen.getByText('The.Grand.Illusion.1937.mkv')
    expect(filenameSpan).toHaveAttribute(
      'title',
      '/media/films/foreign/The.Grand.Illusion.1937.mkv',
    )
  })

  it('renders the PhaseBadge with the job status/phase', () => {
    render(
      <JobRow
        job={makeJob({ status: 'processing', phase: 'transcribing' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByLabelText('Phase: Transcribing')).toBeInTheDocument()
  })

  it('renders an Auto source badge when source === watch_folder', () => {
    render(
      <JobRow job={makeJob({ source: 'watch_folder' })} selected={false} onSelect={() => {}} />,
    )
    expect(screen.getByLabelText(/Source: auto-detected/)).toHaveTextContent('Auto')
  })

  it('omits the Auto badge for manually-submitted jobs', () => {
    render(<JobRow job={makeJob({ source: 'manual' })} selected={false} onSelect={() => {}} />)
    expect(screen.queryByText('Auto')).not.toBeInTheDocument()
  })

  it('renders a partial SSE-announced job (undefined source) without crashing', () => {
    // jobStore.applyJobUpdate inserts unknown-ID updates as partial rows:
    // every field outside the payload — including source — is undefined
    // until the next queue_state replay. Rendering that window crashed
    // prod on 2026-07-15 ("cannot read properties of undefined").
    const partial = makeJob({})
    // @ts-expect-error — simulating the store's documented partial-row cast
    partial.source = undefined
    render(<JobRow job={partial} selected={false} onSelect={() => {}} />)
    expect(screen.queryByText('Auto-retry')).not.toBeInTheDocument()
  })

  it('renders an Auto-retry badge for auto-regen jobs', () => {
    render(
      <JobRow job={makeJob({ source: 'auto-regen:orig-1' })} selected={false} onSelect={() => {}} />,
    )
    expect(screen.getByLabelText(/Source: automatic retry/)).toHaveTextContent('Auto-retry')
  })

  it('renders a progressbar reflecting the current progress value', () => {
    render(
      <JobRow
        job={makeJob({ progress: 42, status: 'processing', phase: 'transcribing' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('value', '42')
  })

  it('omits the progress bar at 0 progress for queued jobs', () => {
    render(
      <JobRow
        job={makeJob({ progress: 0, status: 'queued', phase: null })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('shows full progress bar for completed jobs even at progress=0', () => {
    // The worker emits 100 at completion; this guard is for safety against stale state
    render(
      <JobRow
        job={makeJob({ progress: 100, status: 'completed', completed_at: '2026-04-29T12:01:00Z' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('value', '100')
  })

  it('shows live elapsed time for active jobs (created_at → now)', () => {
    render(
      <JobRow
        job={makeJob({
          created_at: '2026-04-29T12:00:00Z',
          completed_at: null,
          status: 'processing',
          phase: 'transcribing',
        })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('5m 0s')).toBeInTheDocument()
  })

  it('shows static elapsed time for completed jobs (created_at → completed_at)', () => {
    render(
      <JobRow
        job={makeJob({
          created_at: '2026-04-29T12:00:00Z',
          completed_at: '2026-04-29T12:02:30Z',
          status: 'completed',
          progress: 100,
        })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('2m 30s')).toBeInTheDocument()
  })

  it('calls onSelect with the job id when the row is clicked', () => {
    const onSelect = vi.fn()
    render(<JobRow job={makeJob({ id: 'job-xyz' })} selected={false} onSelect={onSelect} />)
    fireEvent.click(getRowButton())
    expect(onSelect).toHaveBeenCalledWith('job-xyz')
  })

  it('applies selected styling when selected=true', () => {
    render(<JobRow job={makeJob()} selected={true} onSelect={() => {}} />)
    const row = getRowButton()
    expect(row.className).toContain('bg-secondary')
    expect(row.className).toContain('border-primary')
    expect(row).toHaveAttribute('aria-pressed', 'true')
  })

  it('falls back to updated_at for terminal jobs missing completed_at (no forever-tick)', () => {
    render(
      <JobRow
        job={makeJob({
          status: 'failed',
          progress: 60,
          created_at: '2026-04-29T12:00:00Z',
          updated_at: '2026-04-29T12:00:45Z',
          completed_at: null,
        })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('45s')).toBeInTheDocument()
  })
})

describe('JobRow — Cancel / Remove flow', () => {
  beforeEach(async () => {
    const { cancelOrRemoveJob } = await import('@/lib/api')
    vi.mocked(cancelOrRemoveJob).mockReset()
  })

  it('shows the X cancel control on queued jobs', () => {
    render(
      <JobRow job={makeJob({ status: 'queued' })} selected={false} onSelect={() => {}} />,
    )
    expect(screen.getByLabelText(/Remove .+\.mkv/i)).toBeInTheDocument()
  })

  it('shows the X cancel control on processing jobs with "Cancel" label', () => {
    render(
      <JobRow
        job={makeJob({ status: 'processing', phase: 'transcribing' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByLabelText(/Cancel .+\.mkv/i)).toBeInTheDocument()
  })

  it('hides the X cancel control on terminal jobs', () => {
    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      const { unmount } = render(
        <JobRow
          job={makeJob({
            status,
            progress: 100,
            completed_at: status === 'completed' ? '2026-04-29T12:01:00Z' : null,
          })}
          selected={false}
          onSelect={() => {}}
        />,
      )
      expect(screen.queryByLabelText(/Remove|Cancel /i)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('opens ConfirmDialog with "Remove" copy for queued jobs', () => {
    render(
      <JobRow job={makeJob({ status: 'queued' })} selected={false} onSelect={() => {}} />,
    )
    fireEvent.click(screen.getByLabelText(/Remove .+\.mkv/i))
    expect(screen.getByText(/^Remove .+\.mkv\?$/)).toBeInTheDocument()
    expect(screen.getByText(/will be removed from the queue/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('opens ConfirmDialog with "Cancel Job" copy for processing jobs', () => {
    render(
      <JobRow
        job={makeJob({ status: 'processing', phase: 'transcribing' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    fireEvent.click(screen.getByLabelText(/Cancel .+\.mkv/i))
    expect(screen.getByText(/^Cancel .+\.mkv\?$/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel Job' })).toBeInTheDocument()
  })

  it('does NOT call onSelect when the cancel control is clicked (stopPropagation)', () => {
    const onSelect = vi.fn()
    render(
      <JobRow job={makeJob({ status: 'queued' })} selected={false} onSelect={onSelect} />,
    )
    fireEvent.click(screen.getByLabelText(/Remove .+\.mkv/i))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('calls cancelOrRemoveJob and shows a success toast when the user confirms', async () => {
    const { cancelOrRemoveJob } = await import('@/lib/api')
    vi.mocked(cancelOrRemoveJob).mockResolvedValue(undefined)
    render(
      <>
        <JobRow
          job={makeJob({ id: 'job-xyz', status: 'queued' })}
          selected={false}
          onSelect={() => {}}
        />
        <Toaster />
      </>,
    )
    fireEvent.click(screen.getByLabelText(/Remove .+\.mkv/i))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await vi.waitFor(() =>
      expect(vi.mocked(cancelOrRemoveJob)).toHaveBeenCalledWith('job-xyz'),
    )
    await vi.waitFor(() => expect(screen.getByText(/^Removed /)).toBeInTheDocument())
  })

  it('shows an error toast when the API call fails', async () => {
    const { cancelOrRemoveJob, ApiRequestError } = await import('@/lib/api')
    vi.mocked(cancelOrRemoveJob).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Internal server error'),
    )
    render(
      <>
        <JobRow
          job={makeJob({ status: 'processing', phase: 'transcribing' })}
          selected={false}
          onSelect={() => {}}
        />
        <Toaster />
      </>,
    )
    fireEvent.click(screen.getByLabelText(/Cancel .+\.mkv/i))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel Job' }))

    await vi.waitFor(() =>
      expect(screen.getByText('Internal server error')).toBeInTheDocument(),
    )
  })
})

describe('JobRow — Retry flow', () => {
  beforeEach(async () => {
    // Mirror the outer describe's fake-timer setup. Without it, Date.now()
    // returns the real wall clock and any test-fixed updated_at value looks
    // ancient — flipping useIsStaleQueued true for "fresh" queued cases.
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:05:00Z'))
    const { retryJob } = await import('@/lib/api')
    vi.mocked(retryJob).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the Retry button on failed jobs and hides it on fresh-queued / processing / completed / cancelled', () => {
    const { unmount } = render(
      <JobRow
        job={makeJob({ status: 'failed', completed_at: null })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByLabelText(/Retry .+\.mkv/)).toBeInTheDocument()
    unmount()

    // For the "queued" case, force updated_at to be _now_ so the row is
    // explicitly fresh (under the 30-second staleness threshold). The
    // stale-queued variant gets its own test below.
    const now = '2026-04-29T12:05:00Z' // matches the vi.setSystemTime in beforeEach
    for (const status of ['queued', 'processing', 'completed', 'cancelled'] as const) {
      const { unmount: unmount2 } = render(
        <JobRow
          job={makeJob({
            status,
            progress: status === 'completed' ? 100 : 0,
            updated_at: now,
          })}
          selected={false}
          onSelect={() => {}}
        />,
      )
      expect(screen.queryByLabelText(/^Retry /)).not.toBeInTheDocument()
      unmount2()
    }
  })

  it('shows the Retry button on a queued job that has been stuck > 30s (orphan recovery)', () => {
    // Row was last touched at 12:04:00 and "now" is 12:05:00 → 60 seconds
    // stale, well past the 30 s recovery threshold.
    render(
      <JobRow
        job={makeJob({ status: 'queued', updated_at: '2026-04-29T12:04:00Z' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByLabelText(/Retry .+\.mkv/)).toBeInTheDocument()
    // Stale-queued tooltip distinguishes the cause from a normal "failed
    // job retry" so the user knows why the affordance appeared.
    expect(screen.getByLabelText(/Retry .+\.mkv/)).toHaveAttribute(
      'title',
      expect.stringMatching(/queued too long/i) as unknown as string,
    )
  })

  it('shows BOTH cancel and retry on a stale-queued row, retry at right edge', () => {
    // Same scenario as above — the user should have the choice between
    // "remove the orphan" (cancel/X) and "retry the orphan" (RotateCw).
    render(
      <JobRow
        job={makeJob({ status: 'queued', updated_at: '2026-04-29T12:04:00Z' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByLabelText(/Remove .+\.mkv/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Retry .+\.mkv/)).toBeInTheDocument()
  })

  it('opens the RetryDialog when the retry icon is clicked', () => {
    render(
      <JobRow
        job={makeJob({ status: 'failed', model_size: 'large-v3' })}
        selected={false}
        onSelect={() => {}}
      />,
    )
    fireEvent.click(screen.getByLabelText(/Retry .+\.mkv/))
    expect(screen.getByText(/^Retry .+\.mkv\?$/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    // The smaller-model branch was removed — retry always uses current Settings.
    expect(
      screen.queryByRole('button', { name: /smaller model/i }),
    ).not.toBeInTheDocument()
  })

  it('calls retryJob with no body and shows a success toast', async () => {
    const { retryJob } = await import('@/lib/api')
    vi.mocked(retryJob).mockResolvedValue(undefined)
    render(
      <>
        <JobRow
          job={makeJob({ id: 'failed-1', status: 'failed', model_size: 'large-v3' })}
          selected={false}
          onSelect={() => {}}
        />
        <Toaster />
      </>,
    )
    fireEvent.click(screen.getByLabelText(/Retry .+\.mkv/))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await vi.waitFor(() =>
      expect(vi.mocked(retryJob)).toHaveBeenCalledWith('failed-1'),
    )
    await vi.waitFor(() => expect(screen.getByText(/^Retrying /)).toBeInTheDocument())
  })

  it('shows an error toast when retryJob fails', async () => {
    const { retryJob, ApiRequestError } = await import('@/lib/api')
    vi.mocked(retryJob).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Backend exploded'),
    )
    render(
      <>
        <JobRow
          job={makeJob({ status: 'failed' })}
          selected={false}
          onSelect={() => {}}
        />
        <Toaster />
      </>,
    )
    fireEvent.click(screen.getByLabelText(/Retry .+\.mkv/))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await vi.waitFor(() => expect(screen.getByText('Backend exploded')).toBeInTheDocument())
  })
})
