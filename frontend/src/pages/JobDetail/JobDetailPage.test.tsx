import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiRequestError, getJob, getJobLog, reverifyJob } from '@/lib/api'
import { makeJob } from '@/test-utils/mockJob'
import { useJobStore } from '@/store/jobStore'
import JobDetailPage from './JobDetailPage'

vi.mock('@/lib/api', async (orig) => {
  const actual = await orig<typeof import('@/lib/api')>()
  return {
    ...actual,
    getJob: vi.fn(),
    getJobLog: vi.fn(),
    reverifyJob: vi.fn(),
  }
})

function renderJobDetail(jobId = 'abc-123') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/jobs/:id', element: <JobDetailPage /> },
      { path: '/history', element: <div>history-page</div> },
    ],
    { initialEntries: [`/jobs/${jobId}`] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getJob).mockReset()
  vi.mocked(getJobLog).mockReset()
  vi.mocked(reverifyJob).mockReset()
  useJobStore.setState({ jobs: [] })
})

describe('JobDetailPage', () => {
  it('renders metadata, pipeline timeline, and log content (AC1)', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        file_path: '/mnt/nas/Foo.mkv',
        status: 'completed',
        phase: 'done',
        target_language: 'en',
        model_size: 'large-v3',
        created_at: '2026-04-24T09:14:00Z',
        completed_at: '2026-04-24T09:36:00Z',
        updated_at: '2026-04-24T09:36:00Z',
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('2026-04-24T09:14:02Z INFO  [job:abc] Job started\n')
    renderJobDetail('abc-123')

    expect(await screen.findByRole('heading', { level: 1, name: 'Foo.mkv' })).toBeInTheDocument()
    expect(screen.getAllByText('large-v3').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByLabelText('Pipeline status')).toBeInTheDocument()
    expect(await screen.findByText('Job started')).toBeInTheDocument()
  })

  it('shows the CompletionCard for completed jobs (AC3)', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'completed', target_language: 'en', completed_at: '2026-04-24T09:36:00Z' }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail()
    expect(await screen.findByText('Output File')).toBeInTheDocument()
  })

  it('shows the ErrorCard for failed jobs (AC4)', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ status: 'failed', phase: 'transcribing', error_message: 'CUDA OOM' }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail()
    expect(await screen.findByText(/Job failed during Transcribing/)).toBeInTheDocument()
  })

  it('shows Job not found state when getJob 404s (AC5)', async () => {
    vi.mocked(getJob).mockRejectedValue(new ApiRequestError(404, 'JOB_NOT_FOUND', 'Job not found'))
    renderJobDetail('does-not-exist')
    expect(await screen.findByRole('heading', { level: 1, name: 'Job not found.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to History/ })).toHaveAttribute('href', '/history')
  })

  it('Download Full Log link points to the history log endpoint (AC2)', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob({ id: 'abc-123', status: 'completed' }))
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')
    const link = await screen.findByRole('link', { name: /Download Full Log/ })
    expect(link).toHaveAttribute('href', '/api/v1/history/abc-123/log')
    expect(link).toHaveAttribute('download', 'abc-123.log')
  })

  it('falls back gracefully when getJobLog 404s (queued job, no log file yet)', async () => {
    vi.mocked(getJob).mockResolvedValue(makeJob({ status: 'queued' }))
    vi.mocked(getJobLog).mockRejectedValue(new ApiRequestError(404, 'LOG_NOT_FOUND', 'Log not found'))
    renderJobDetail()
    // Synthetic line still appears because rawLog is undefined
    expect(await screen.findByText(/Job received\. Initializing pipeline/)).toBeInTheDocument()
  })

  it('shows verification panel with check name and Re-verify button when verification_status is set', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        status: 'completed',
        verification_status: 'warn',
        verification_score: 60,
        verification_report: {
          summary: 'WARN — 0 fail, 1 warn',
          checks: [{ layer: 'heuristic', name: 'repeat_loop', severity: 'warn', detail: 'longest run: 7' }],
        },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    vi.mocked(reverifyJob).mockResolvedValue(undefined)
    renderJobDetail('abc-123')

    expect(await screen.findByText(/repeat_loop/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-verify/i })).toBeInTheDocument()
  })

  it('links to the automatic retry when the report carries auto_retry_job_id', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        status: 'completed',
        verification_status: 'fail',
        verification_score: 20,
        verification_report: {
          summary: 'FAIL — 1 fail',
          checks: [{ layer: 'structural', name: 'min_cues', severity: 'fail', detail: 'only 2 cues' }],
          auto_retry_job_id: 'retry-456',
        },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    vi.mocked(reverifyJob).mockResolvedValue(undefined)
    renderJobDetail('abc-123')

    expect(await screen.findByText(/fresh attempt was started automatically/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view the retry/i })).toHaveAttribute('href', '/jobs/retry-456')
  })

  it('shows existing-subtitles provenance when source_srt_path is set', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ id: 'j-es', status: 'completed', source_srt_path: '/media/Film.en.srt' }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('j-es')

    expect(await screen.findByText(/Sourced from an existing subtitle track/)).toBeInTheDocument()
    expect(screen.getByText('Film.en.srt')).toBeInTheDocument()
  })

  it('shows provenance back to the original job on an auto-regen run', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ id: 'retry-456', status: 'processing', source: 'auto-regen:abc-123' }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('retry-456')

    expect(await screen.findByText(/Automatic retry of a run/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view the original job/i })).toHaveAttribute('href', '/jobs/abc-123')
  })

  it('renders plain-language issues and collapses the rest', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        status: 'completed',
        verification_status: 'warn',
        verification_score: 80,
        verification_report: {
          summary: 'WARN — 0 fail, 1 warn across 10 checks',
          checks: [
            { layer: 'structural', name: 'non_empty', severity: 'ok', detail: '' },
            { layer: 'structural', name: 'coverage', severity: 'ok', detail: 'subtitles cover 96% of runtime' },
            { layer: 'heuristic', name: 'reading_speed', severity: 'warn', detail: '12/386 cues exceed 35.0 cps' },
          ],
        },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    vi.mocked(reverifyJob).mockResolvedValue(undefined)
    renderJobDetail('abc-123')

    expect(await screen.findByText('Worth a look')).toBeInTheDocument()
    expect(screen.getByText(/Some lines may be fast to read/)).toBeInTheDocument()
    expect(screen.getByText(/2 other checks passed/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-verify/i })).toBeInTheDocument()
  })

  it('shows raw check names under See all details', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123', status: 'completed', verification_status: 'warn', verification_score: 80,
        verification_report: { summary: 's', checks: [
          { layer: 'heuristic', name: 'reading_speed', severity: 'warn', detail: '12/386 cues exceed 35.0 cps' },
        ] },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')
    // <details> content is in the DOM even when collapsed
    expect(await screen.findByText('reading_speed')).toBeInTheDocument()
  })

  it('pass verdict shows green headline and no issue list', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123', status: 'completed', verification_status: 'pass', verification_score: 100,
        verification_report: { summary: 'PASS', checks: [
          { layer: 'structural', name: 'non_empty', severity: 'ok', detail: '' },
        ] },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')
    expect(await screen.findByText('Looks good')).toBeInTheDocument()
    expect(screen.getByText(/1 other check passed/)).toBeInTheDocument()
  })

  it('shows the repeated line evidence when a repeat_loop check carries it', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123', status: 'completed', verification_status: 'warn', verification_score: 70,
        verification_report: { summary: 'WARN', checks: [
          { layer: 'heuristic', name: 'repeat_loop', severity: 'warn',
            detail: 'longest identical-line run: 48',
            repeated: { text: '— Jimsy.', start: 2283, end: 2342, count: 48 } },
        ] },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')
    const toggle = await screen.findByText(/show the repeated line/i)
    fireEvent.click(toggle)
    expect(screen.getByText(/— Jimsy\./)).toBeInTheDocument()
    expect(screen.getByText(/48×/)).toBeInTheDocument()
    expect(screen.getByText(/38:03/)).toBeInTheDocument()
  })

  it('overlays a live verification verdict from the job store (post-Re-verify SSE)', async () => {
    // react-query snapshot has NO verdict yet (job completed before verification)
    vi.mocked(getJob).mockResolvedValue(
      makeJob({ id: 'abc-123', status: 'completed', verification_status: null }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    // the live SSE job_update (partial) arrives in the store with a verdict
    useJobStore.setState({
      jobs: [{
        id: 'abc-123',
        verification_status: 'fail',
        verification_score: 20,
        verification_report: {
          summary: 'FAIL — 1 fail',
          checks: [{ layer: 'heuristic', name: 'repeat_loop', severity: 'fail', detail: 'longest run: 40' }],
        },
      } as never],
    })
    renderJobDetail('abc-123')

    // the panel reflects the LIVE verdict, not the (null) query snapshot
    expect(await screen.findByText(/repeat_loop/)).toBeInTheDocument()
    expect(screen.getByText(/longest run: 40/)).toBeInTheDocument()
  })
})

  it('renders the quality scorecard when the report carries metrics (WS11)', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        status: 'completed',
        verification_status: 'pass',
        verification_score: 100,
        verification_report: {
          summary: 'PASS',
          checks: [{ layer: 'structural', name: 'non_empty', severity: 'ok', detail: '' }],
          metrics: {
            cue_count: 1284,
            coverage_ratio: 0.87,
            cps_p50: 12.1,
            cps_p95: 22.4,
            cps_max: 31.0,
            pct_cues_over_20cps: 6.2,
            min_duration: 0.91,
            gaps_over_90s: 1,
            max_gap: 112.4,
          },
        },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')

    const card = await screen.findByTestId('quality-scorecard')
    expect(card).toBeInTheDocument()
    expect(screen.getByText('22.4')).toBeInTheDocument()
    expect(screen.getByText('87')).toBeInTheDocument()
    expect(screen.getByText('1,284')).toBeInTheDocument()
    // breached thresholds render in the alert tone
    expect(screen.getByText('22.4').className).toContain('text-amber-400')
    expect(screen.getByText('6.2').className).toContain('text-amber-400')
    expect(screen.getByText('1,284').className).not.toContain('text-amber-400')
  })

  it('omits the scorecard when the report has no metrics (older jobs)', async () => {
    vi.mocked(getJob).mockResolvedValue(
      makeJob({
        id: 'abc-123',
        status: 'completed',
        verification_status: 'pass',
        verification_score: 100,
        verification_report: {
          summary: 'PASS',
          checks: [{ layer: 'structural', name: 'non_empty', severity: 'ok', detail: '' }],
        },
      }),
    )
    vi.mocked(getJobLog).mockResolvedValue('')
    renderJobDetail('abc-123')
    await screen.findByRole('button', { name: /re-verify/i })
    expect(screen.queryByTestId('quality-scorecard')).not.toBeInTheDocument()
  })
