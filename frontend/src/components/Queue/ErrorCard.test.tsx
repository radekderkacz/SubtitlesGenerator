import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Toaster } from '@/components/ui/sonner'
import ErrorCard from './ErrorCard'
import { makeJob } from '@/test-utils/mockJob'

vi.mock('@/lib/api', () => ({
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

describe('ErrorCard', () => {
  beforeEach(async () => {
    const { retryJob } = await import('@/lib/api')
    vi.mocked(retryJob).mockReset()
  })

  it('shows the phase label where the job failed', () => {
    render(
      <ErrorCard
        job={makeJob({
          status: 'failed',
          phase: 'transcribing',
          error_message: 'CUDA out of memory',
        })}
      />,
    )
    expect(screen.getByText(/Job failed during Transcribing/)).toBeInTheDocument()
  })

  it('shows "Pre-pickup" when phase is null', () => {
    render(
      <ErrorCard
        job={makeJob({
          status: 'failed',
          phase: null,
          error_message: 'Worker crashed before pickup',
        })}
      />,
    )
    expect(screen.getByText(/Job failed during Pre-pickup/)).toBeInTheDocument()
  })

  it('renders the error message in a code block', () => {
    render(
      <ErrorCard
        job={makeJob({
          status: 'failed',
          error_message: 'ffmpeg: codec not found',
        })}
      />,
    )
    expect(screen.getByText('ffmpeg: codec not found')).toBeInTheDocument()
  })

  it('falls back when error_message is null', () => {
    render(<ErrorCard job={makeJob({ status: 'failed', error_message: null })} />)
    expect(screen.getByText('No error message recorded.')).toBeInTheDocument()
  })

  it('opens the RetryDialog when Retry is clicked', () => {
    render(
      <ErrorCard
        job={makeJob({ status: 'failed', model_size: 'large-v3' })}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    expect(screen.getByText(/^Retry .+\.mkv\?$/)).toBeInTheDocument()
    // Smaller-model branch removed — retry always uses current Settings.
    expect(
      screen.queryByRole('button', { name: /smaller model/i }),
    ).not.toBeInTheDocument()
  })

  it('calls retryJob and shows a toast when the user confirms', async () => {
    const { retryJob } = await import('@/lib/api')
    vi.mocked(retryJob).mockResolvedValue(undefined)
    render(
      <>
        <ErrorCard
          job={makeJob({
            id: 'job-fail',
            file_path: '/media/Film.mkv',
            status: 'failed',
            model_size: 'medium',
          })}
        />
        <Toaster />
      </>,
    )
    fireEvent.click(screen.getByRole('button', { name: /^Retry$/ }))
    // Two "Retry" buttons exist briefly while the dialog is open. The outer
    // one was the trigger; the inner Dialog button is what fires retryJob.
    const dialogRetry = screen.getAllByRole('button', { name: 'Retry' }).pop()!
    fireEvent.click(dialogRetry)
    await vi.waitFor(() =>
      expect(vi.mocked(retryJob)).toHaveBeenCalledWith('job-fail'),
    )
  })
})
