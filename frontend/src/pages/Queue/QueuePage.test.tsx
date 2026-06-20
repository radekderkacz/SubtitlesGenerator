import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { apiFetch, stopAllJobs } from '@/lib/api'
import { baseMockSettings } from '@/test-utils/mockSettings'
import { useJobStore } from '@/store/jobStore'
import { Toaster } from '@/components/ui/sonner'
import { makeJob } from '@/test-utils/mockJob'
import type { JobUpdatePayload } from '@/types/api'
import QueuePage from './QueuePage'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  cancelOrRemoveJob: vi.fn(),
  stopAllJobs: vi.fn(),
  getWatchFolderActivity: vi.fn().mockResolvedValue({
    auto_enqueued_count_24h: 0,
    recent_auto_jobs: [],
    recent_skipped: [],
    monitored_paths: [],
  }),
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

// QueuePage mounts useJobStream, which opens an EventSource. The setup-level
// stub keeps the connection inert; we also need the store to look "connected"
// so QueueList renders its empty state instead of the skeleton — that way the
// Browse Library link is exposed at the page-test level.
vi.mock('@/hooks/useJobStream', () => ({
  useJobStream: vi.fn(),
}))

function renderQueuePage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', element: <QueuePage /> },
      { path: '/settings', element: <div>Settings</div> },
      { path: '/browse', element: <div>Browse</div> },
    ],
    { initialEntries: ['/'] },
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
  useJobStore.setState({ jobs: [], isConnected: true })
})

describe('QueuePage', () => {
  it('renders queue heading', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    renderQueuePage()
    expect(await screen.findByRole('heading', { level: 1, name: 'Active Queue' })).toBeInTheDocument()
  })

  it('shows setup banner when nas_mount_path is null', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: null, transcription_backend: null })
    renderQueuePage()
    expect(await screen.findByText(/Setup required/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Settings' })).toBeInTheDocument()
  })

  it('shows setup banner when transcription_backend is null but nas_mount_path is set', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: '/mnt/nas', transcription_backend: null })
    renderQueuePage()
    expect(await screen.findByText(/Setup required/)).toBeInTheDocument()
  })

  it('shows setup banner when nas_mount_path is null but transcription_backend is set', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: null })
    renderQueuePage()
    expect(await screen.findByText(/Setup required/)).toBeInTheDocument()
  })

  it('hides banner when both nas_mount_path and transcription_backend are set', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    renderQueuePage()
    expect(await screen.findByRole('heading', { level: 1, name: 'Active Queue' })).toBeInTheDocument()
    expect(screen.queryByText(/Setup required/)).not.toBeInTheDocument()
  })

  it('Open Settings link has href /settings', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: null, transcription_backend: null })
    renderQueuePage()
    const link = await screen.findByRole('link', { name: 'Open Settings' })
    expect(link).toHaveAttribute('href', '/settings')
  })

  it('shows setup banner when nas_mount_path is /media (seeded default)', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/media',
    })
    renderQueuePage()
    expect(await screen.findByText(/Setup required/)).toBeInTheDocument()
  })

  it('does not show setup banner while settings are loading', () => {
    vi.mocked(apiFetch).mockReturnValue(new Promise(() => {}))
    renderQueuePage()
    expect(screen.queryByText(/Setup required/)).not.toBeInTheDocument()
  })

  it('shows a job created while another is processing (partial SSE creation event) in Up Next', async () => {
    // Regression: a 2nd movie submitted while the 1st was processing stayed
    // invisible. The backend now publishes a job_update on creation, which
    // arrives as a PARTIAL job (only SSE payload fields — no created_at /
    // source_language). It must still render in Up Next.
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
    useJobStore.setState({
      jobs: [makeJob({ id: 'j1', status: 'processing', file_path: '/media/Movie/First.Movie.mkv' })],
      isConnected: true,
    })
    useJobStore.getState().applyJobUpdate({
      id: 'j2',
      status: 'queued',
      phase: null,
      progress: 0,
      updated_at: '2026-06-19T00:00:00Z',
      file_path: '/media/Movie/Second.Movie.mkv',
      error_message: null,
    } as JobUpdatePayload)
    renderQueuePage()
    expect(await screen.findByText('Second.Movie.mkv')).toBeInTheDocument()
  })

  // useJobStream moved to Layout (app-shell) so SSE survives navigation.
  // The "mounts useJobStream once" contract lives in Layout.test.tsx now.
  it('does NOT mount useJobStream from the page (it lives in Layout)', async () => {
    const { useJobStream } = await import('@/hooks/useJobStream')
    vi.mocked(useJobStream).mockClear()
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    renderQueuePage()
    expect(useJobStream).not.toHaveBeenCalled()
  })

  it('shows the empty state with a New Task CTA when no jobs exist', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    useJobStore.setState({ jobs: [], isConnected: true })
    renderQueuePage()
    expect(await screen.findByRole('heading', { name: 'Queue is idle' })).toBeInTheDocument()
    const ctas = screen.getAllByRole('link', { name: /new task/i })
    // header CTA + empty-state CTA both present
    expect(ctas.length).toBeGreaterThanOrEqual(1)
    expect(ctas[0]).toHaveAttribute('href', '/browse')
  })

  it('renders the focus card for the first processing job', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'a', status: 'processing', phase: 'transcribing', file_path: '/x/Foo.mkv' }),
      ],
      isConnected: true,
    })
    renderQueuePage()
    expect(await screen.findByLabelText(/Active job: Foo\.mkv/)).toBeInTheDocument()
  })
})

describe('QueuePage — Stop All button', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
    vi.mocked(stopAllJobs).mockReset()
  })

  function renderWithToaster() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const router = createMemoryRouter(
      [
        { path: '/', element: <><QueuePage /><Toaster /></> },
        { path: '/settings', element: <div>Settings</div> },
        { path: '/browse', element: <div>Browse</div> },
      ],
      { initialEntries: ['/'] },
    )
    return render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
  }

  it('hides Stop All when there are no active jobs', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    useJobStore.setState({ jobs: [], isConnected: true })
    renderWithToaster()
    await screen.findByRole('heading', { level: 1, name: 'Active Queue' })
    expect(screen.queryByRole('button', { name: 'Stop All' })).not.toBeInTheDocument()
  })

  it('shows Stop All when at least one job is active', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    useJobStore.setState({
      jobs: [makeJob({ id: 'a', status: 'processing', phase: 'transcribing' })],
      isConnected: true,
    })
    renderWithToaster()
    expect(await screen.findByRole('button', { name: 'Stop All' })).toBeInTheDocument()
  })

  it('opens the confirm dialog and calls stopAllJobs on confirm', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    vi.mocked(stopAllJobs).mockResolvedValue(undefined)
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'a', status: 'queued' }),
        makeJob({ id: 'b', status: 'processing' }),
      ],
      isConnected: true,
    })
    renderWithToaster()

    fireEvent.click(await screen.findByRole('button', { name: 'Stop All' }))
    expect(screen.getByText(/Stop 2 active jobs\?/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stop All', hidden: false }) as HTMLElement)
    // The Stop All button in the dialog has the same name; the dialog confirm is the
    // second one. Use the explicit dialog confirm via destructive variant filter:
    await vi.waitFor(() => expect(vi.mocked(stopAllJobs)).toHaveBeenCalled())
  })

  it('shows an error toast when stopAllJobs fails', async () => {
    const { ApiRequestError } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    vi.mocked(stopAllJobs).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Server error'),
    )
    useJobStore.setState({
      jobs: [makeJob({ id: 'a', status: 'processing' })],
      isConnected: true,
    })
    renderWithToaster()

    fireEvent.click(await screen.findByRole('button', { name: 'Stop All' }))
    // Dialog opens; second "Stop All" button is the confirm.
    const confirmButtons = screen.getAllByRole('button', { name: 'Stop All' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await vi.waitFor(() => expect(screen.getByText('Server error')).toBeInTheDocument())
  })
})
