import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { getWatchFolderActivity } from '@/lib/api'
import { useJobStore } from '@/store/jobStore'
import { makeJob } from '@/test-utils/mockJob'
import { makeHistoryEntry } from '@/test-utils/mockHistoryEntry'
import WatchFolderPanel from './WatchFolderPanel'
import type { WatchFolderActivity } from '@/types/api'

vi.mock('@/lib/api', async (orig) => {
  const actual = await orig<typeof import('@/lib/api')>()
  return { ...actual, getWatchFolderActivity: vi.fn() }
})

function makeActivity(overrides: Partial<WatchFolderActivity> = {}): WatchFolderActivity {
  return {
    auto_enqueued_count_24h: 0,
    recent_auto_jobs: [],
    recent_skipped: [],
    monitored_paths: [],
    ...overrides,
  }
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/', element: <WatchFolderPanel /> },
      { path: '/jobs/:id', element: <div>job-detail</div> },
    ],
    { initialEntries: ['/'] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getWatchFolderActivity).mockReset()
  useJobStore.setState({ jobs: [], isConnected: true })
})

describe('WatchFolderPanel', () => {
  it('renders the section header', async () => {
    vi.mocked(getWatchFolderActivity).mockResolvedValue(makeActivity())
    renderPanel()
    expect(
      await screen.findByRole('button', { name: /Watch Folder Activity/ }),
    ).toBeInTheDocument()
  })

  it('shows the empty state when no activity in the last 24h', async () => {
    vi.mocked(getWatchFolderActivity).mockResolvedValue(makeActivity())
    renderPanel()
    // Force expand
    fireEvent.click(await screen.findByRole('button', { name: /Watch Folder Activity/ }))
    expect(
      await screen.findByText('No files detected in the last 24 hours.'),
    ).toBeInTheDocument()
  })

  it('lists recent auto-enqueued jobs and skipped paths', async () => {
    vi.mocked(getWatchFolderActivity).mockResolvedValue(
      makeActivity({
        auto_enqueued_count_24h: 2,
        recent_auto_jobs: [
          makeHistoryEntry({ id: 'a', file_path: '/x/AutoOne.mkv' }),
          makeHistoryEntry({ id: 'b', file_path: '/x/AutoTwo.mkv' }),
        ],
        recent_skipped: [{ path: '/x/AlreadyDone.mkv', skipped_at: '2026-05-08T12:00:00Z' }],
        monitored_paths: ['/media/incoming'],
      }),
    )
    renderPanel()
    // Auto-expanded since queue is empty + activity exists
    expect(await screen.findByText('AutoOne.mkv')).toBeInTheDocument()
    expect(screen.getByText('AutoTwo.mkv')).toBeInTheDocument()
    expect(screen.getByText('AlreadyDone.mkv')).toBeInTheDocument()
    expect(screen.getByText('/media/incoming')).toBeInTheDocument()
    // Header chip shows the 24h count
    expect(screen.getByText('2', { selector: 'span' })).toBeInTheDocument()
  })

  it('starts collapsed when there are active jobs', async () => {
    useJobStore.setState({
      jobs: [makeJob({ id: 'a', status: 'processing' })],
      isConnected: true,
    })
    vi.mocked(getWatchFolderActivity).mockResolvedValue(
      makeActivity({
        auto_enqueued_count_24h: 1,
        recent_auto_jobs: [makeHistoryEntry({ id: 'a', file_path: '/x/Auto.mkv' })],
      }),
    )
    renderPanel()
    await waitFor(() => expect(getWatchFolderActivity).toHaveBeenCalled())
    // Body should be collapsed → file name not visible
    expect(screen.queryByText('Auto.mkv')).not.toBeInTheDocument()
    // Click to expand
    fireEvent.click(screen.getByRole('button', { name: /Watch Folder Activity/ }))
    expect(await screen.findByText('Auto.mkv')).toBeInTheDocument()
  })
})
