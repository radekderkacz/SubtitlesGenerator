import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { listHistory, deleteHistory } from '@/lib/api'
import type { HistoryEntry } from '@/types/api'
import HistoryPage from './HistoryPage'

vi.mock('@/lib/api', () => ({
  listHistory: vi.fn(),
  deleteHistory: vi.fn(),
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

let _entryCounter = 0
function makeEntry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  _entryCounter += 1
  return {
    id: `job-${_entryCounter}`,
    status: 'completed',
    file_path: '/mnt/nas/films/Foo.mkv',
    source_language: 'fr',
    target_language: 'en',
    model_size: 'large-v3',
    translation_provider: null,
    translation_model: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    cost_usd: null,
    srt_path: '/mnt/nas/films/Foo.en.srt',
    error_message: null,
    created_at: '2026-04-24T09:14:00Z',
    updated_at: '2026-04-24T09:36:00Z',
    completed_at: '2026-04-24T09:36:00Z',
    jellyfin_refreshed_at: null,
    verification_status: null,
    verification_score: null,
    ...overrides,
  }
}

function renderHistoryPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/', element: <HistoryPage /> },
      { path: '/jobs/:id', element: <div>job-detail</div> },
    ],
    { initialEntries: ['/'] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(listHistory).mockReset()
  vi.mocked(deleteHistory).mockReset()
})

describe('HistoryPage', () => {
  it('shows the empty state when no entries exist', async () => {
    vi.mocked(listHistory).mockResolvedValue([])
    renderHistoryPage()
    expect(await screen.findByText('No completed jobs yet.')).toBeInTheDocument()
  })

  it('renders the table when entries exist with correct counts', async () => {
    vi.mocked(listHistory).mockResolvedValue([
      makeEntry({ status: 'completed' }),
      makeEntry({ status: 'completed' }),
      makeEntry({ status: 'failed', error_message: 'oops' }),
      makeEntry({ status: 'cancelled' }),
    ])
    renderHistoryPage()
    await waitFor(() => expect(screen.queryByText(/Loading history/)).not.toBeInTheDocument())
    expect(screen.getByRole('region', { name: 'History entries' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /All\s*4/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Done\s*2/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Failed\s*1/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Cancelled\s*1/ })).toBeInTheDocument()
  })

  it('clicking a status tab filters the table client-side', async () => {
    vi.mocked(listHistory).mockResolvedValue([
      makeEntry({ id: 'a', status: 'completed', file_path: '/x/Done.mkv' }),
      makeEntry({ id: 'b', status: 'failed', file_path: '/x/Broken.mkv', error_message: 'oops' }),
    ])
    renderHistoryPage()
    await screen.findByText('Done.mkv')
    fireEvent.click(screen.getByRole('tab', { name: /Failed/ }))
    expect(screen.queryByText('Done.mkv')).not.toBeInTheDocument()
    expect(screen.getByText('Broken.mkv')).toBeInTheDocument()
  })

  it('typing in search narrows the visible rows', async () => {
    vi.mocked(listHistory).mockResolvedValue([
      makeEntry({ id: 'a', file_path: '/x/Foo.mkv' }),
      makeEntry({ id: 'b', file_path: '/x/Bar.mkv' }),
    ])
    renderHistoryPage()
    await screen.findByText('Foo.mkv')
    fireEvent.change(screen.getByLabelText('Search history'), { target: { value: 'Bar' } })
    expect(screen.queryByText('Foo.mkv')).not.toBeInTheDocument()
    expect(screen.getByText('Bar.mkv')).toBeInTheDocument()
  })

  it('Clear History opens the confirm dialog and refetches on confirm (AC6)', async () => {
    vi.mocked(listHistory).mockResolvedValueOnce([makeEntry()]).mockResolvedValueOnce([])
    vi.mocked(deleteHistory).mockResolvedValue({ deleted: 1 })
    renderHistoryPage()
    await screen.findByText('Foo.mkv')

    fireEvent.click(screen.getByRole('button', { name: /Clear History/ }))
    expect(await screen.findByText('Clear job history?')).toBeInTheDocument()
    expect(screen.getByText(/Active and queued jobs are not affected/)).toBeInTheDocument()

    const buttons = screen.getAllByRole('button', { name: /Clear History/ })
    fireEvent.click(buttons[buttons.length - 1])
    await waitFor(() => expect(deleteHistory).toHaveBeenCalled())
    // The invalidation should have triggered a second listHistory call —
    // proving the table refreshes after the purge (the second mock returns []).
    await waitFor(() => expect(listHistory).toHaveBeenCalledTimes(2))
    await screen.findByText('No completed jobs yet.')
  })

  it('disables Clear History when the list is empty', async () => {
    vi.mocked(listHistory).mockResolvedValue([])
    renderHistoryPage()
    await screen.findByText('No completed jobs yet.')
    expect(screen.getByRole('button', { name: /Clear History/ })).toBeDisabled()
  })

  it('shows aggregate total tokens and total spend in the stats bento', async () => {
    vi.mocked(listHistory).mockResolvedValue([
      makeEntry({ total_tokens: 1000, cost_usd: 0.01 }),
      makeEntry({ total_tokens: 500, cost_usd: 0.02 }),
      makeEntry({ total_tokens: 250, cost_usd: null }),
    ])
    renderHistoryPage()
    expect(await screen.findByText('1,750')).toBeInTheDocument()   // 1000+500+250
    expect(await screen.findByText('$0.0300')).toBeInTheDocument() // 0.01+0.02 (null→0)
  })

  it('shows the bento stats values derived from the unfiltered list', async () => {
    vi.mocked(listHistory).mockResolvedValue([
      // 22m 16s and 31m 7s — both with model 'large-v3' completed
      makeEntry({ status: 'completed', model_size: 'large-v3', created_at: '2026-04-24T09:14:00Z', completed_at: '2026-04-24T09:36:16Z' }),
      makeEntry({ status: 'completed', model_size: 'large-v3', created_at: '2026-04-23T08:00:00Z', completed_at: '2026-04-23T08:31:07Z' }),
      makeEntry({ status: 'failed', model_size: 'large-v3', error_message: 'oops' }),
    ])
    renderHistoryPage()
    await screen.findByText(/2 completed/)
    const statsRegion = screen.getByRole('region', { name: 'Statistics summary' })
    // Top model = large-v3
    expect(statsRegion).toHaveTextContent('large-v3')
    // 2 done / (2 done + 1 failed) = 66.7%
    expect(statsRegion).toHaveTextContent('66.7%')
  })
})
