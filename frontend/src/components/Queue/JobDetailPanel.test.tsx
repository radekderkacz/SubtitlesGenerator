import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render as rtlRender, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import JobDetailPanel from './JobDetailPanel'
import { makeJob } from '@/test-utils/mockJob'

vi.mock('@/lib/api', () => ({
  retryJob: vi.fn(),
  refreshJellyfin: vi.fn(),
  apiFetch: vi.fn().mockResolvedValue({ jellyfin_url: null, jellyfin_api_key: null }),
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

// Wrap every render in a QueryClientProvider since CompletionCard now reads
// settings via useQuery for the Jellyfin section gate.
function render(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('JobDetailPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the empty state when selectedJob is null', () => {
    render(<JobDetailPanel selectedJob={null} />)
    expect(screen.getByRole('heading', { name: 'Select a job' })).toBeInTheDocument()
  })

  it('renders the header with filename, status badge, ID, and metadata strip', () => {
    render(
      <JobDetailPanel
        selectedJob={makeJob({
          id: 'job-1',
          file_path: '/media/Film.mkv',
          status: 'processing',
          phase: 'transcribing',
          created_at: '2026-04-29T11:00:00Z',
          updated_at: '2026-04-29T11:55:00Z',
          model_size: 'large-v3',
        })}
      />,
    )
    expect(screen.getByText('Film.mkv')).toBeInTheDocument()
    expect(screen.getByText(/^ID: job-1$/)).toBeInTheDocument()
    expect(screen.getByLabelText('Phase: Transcribing')).toBeInTheDocument()
    expect(screen.getByText('large-v3')).toBeInTheDocument()
  })

  it('renders the PhaseTimeline section', () => {
    render(
      <JobDetailPanel
        selectedJob={makeJob({ status: 'processing', phase: 'translating' })}
      />,
    )
    expect(screen.getByLabelText('Pipeline status')).toBeInTheDocument()
  })

  it('shows the CompletionCard for completed jobs', () => {
    render(
      <JobDetailPanel
        selectedJob={makeJob({
          status: 'completed',
          target_language: 'en',
          completed_at: '2026-04-29T11:30:00Z',
        })}
      />,
    )
    expect(screen.getByText('Output File')).toBeInTheDocument()
  })

  it('shows the ErrorCard for failed jobs', () => {
    render(
      <JobDetailPanel
        selectedJob={makeJob({
          status: 'failed',
          phase: 'transcribing',
          error_message: 'CUDA OOM',
        })}
      />,
    )
    expect(screen.getByText(/Job failed during Transcribing/)).toBeInTheDocument()
    // Error message appears both in the ErrorCard and in the live log feed
    expect(screen.getAllByText('CUDA OOM').length).toBeGreaterThanOrEqual(1)
  })

  it('shows neither completion nor error card for queued / processing / cancelled', () => {
    for (const status of ['queued', 'processing', 'cancelled'] as const) {
      const { unmount } = render(
        <JobDetailPanel
          selectedJob={makeJob({ status, phase: status === 'processing' ? 'transcribing' : null })}
        />,
      )
      expect(screen.queryByText('Output File')).not.toBeInTheDocument()
      expect(screen.queryByText(/Job failed during/)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('renders the Live Log Output panel with synthetic lines', () => {
    render(
      <JobDetailPanel selectedJob={makeJob({ status: 'processing', phase: 'transcribing' })} />,
    )
    expect(screen.getByRole('region', { name: 'Live log' })).toBeInTheDocument()
    expect(screen.getByText('Live Log Output')).toBeInTheDocument()
  })

  it('renders the stuck-job footer for processing jobs idle > 30 minutes', () => {
    render(
      <JobDetailPanel
        selectedJob={makeJob({
          status: 'processing',
          phase: 'transcribing',
          updated_at: '2026-04-29T11:00:00Z', // 60 min ago
        })}
      />,
    )
    expect(screen.getByText(/Job appears stuck/)).toBeInTheDocument()
  })
})
