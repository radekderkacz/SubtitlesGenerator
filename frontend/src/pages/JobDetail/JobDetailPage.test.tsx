import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiRequestError, getJob, getJobLog } from '@/lib/api'
import { makeJob } from '@/test-utils/mockJob'
import JobDetailPage from './JobDetailPage'

vi.mock('@/lib/api', async (orig) => {
  const actual = await orig<typeof import('@/lib/api')>()
  return {
    ...actual,
    getJob: vi.fn(),
    getJobLog: vi.fn(),
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
})
