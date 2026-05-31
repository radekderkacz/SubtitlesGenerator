import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

// Mock TanStack Virtual: jsdom can't measure scroll elements so the real
// virtualizer returns no virtual items. The mock returns a virtual item per
// job at row-height offsets — same render shape as production with realistic
// measurements. Production code is unchanged.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => {
    const items = Array.from({ length: count }, (_, index) => ({
      index,
      key: index,
      start: index * 110,
      size: 110,
      end: (index + 1) * 110,
      lane: 0,
    }))
    return {
      getTotalSize: () => count * 110,
      getVirtualItems: () => items,
    }
  },
}))

import QueueList from './QueueList'
import { useJobStore } from '@/store/jobStore'
import { makeJob } from '@/test-utils/mockJob'

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('QueueList', () => {
  beforeEach(() => {
    useJobStore.setState({ jobs: [], isConnected: false })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the skeleton state when SSE is not yet connected', () => {
    useJobStore.setState({ jobs: [], isConnected: false })
    renderWithRouter(<QueueList selectedId={null} onSelect={() => {}} />)
    expect(screen.getByLabelText(/loading jobs/i)).toBeInTheDocument()
  })

  it('renders the empty state when connected but no jobs', () => {
    useJobStore.setState({ jobs: [], isConnected: true })
    renderWithRouter(<QueueList selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText(/no jobs yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /browse library/i })).toHaveAttribute(
      'href',
      '/browse',
    )
  })

  it('renders JobRows when connected with jobs', () => {
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'j1', file_path: '/media/Film.A.mkv' }),
        makeJob({ id: 'j2', file_path: '/media/Film.B.mkv' }),
      ],
      isConnected: true,
    })
    renderWithRouter(<QueueList selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText('Film.A.mkv')).toBeInTheDocument()
    expect(screen.getByText('Film.B.mkv')).toBeInTheDocument()
  })

  it('marks the selected JobRow with aria-pressed=true', () => {
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'j1', file_path: '/media/Film.A.mkv' }),
        makeJob({ id: 'j2', file_path: '/media/Film.B.mkv' }),
      ],
      isConnected: true,
    })
    renderWithRouter(<QueueList selectedId="j2" onSelect={() => {}} />)
    const buttons = screen.getAllByRole('button')
    const selectedButtons = buttons.filter((b) => b.getAttribute('aria-pressed') === 'true')
    expect(selectedButtons).toHaveLength(1)
    expect(selectedButtons[0]).toHaveTextContent('Film.B.mkv')
  })

  it('sorts active jobs oldest-first so the running job anchors at the top (bug #83)', () => {
    // Storage order is newest-first (the order the backend currently returns).
    // The sort comparator must flip that for active jobs so the row that is
    // ACTUALLY being processed sits at the top and the next FIFO pick is
    // directly below it — matching the worker's execution order.
    useJobStore.setState({
      jobs: [
        makeJob({
          id: 'j3',
          file_path: '/E03.mkv',
          status: 'queued',
          created_at: '2026-05-19T23:31:04.647Z',
        }),
        makeJob({
          id: 'j2',
          file_path: '/E02.mkv',
          status: 'queued',
          created_at: '2026-05-19T23:31:04.491Z',
        }),
        makeJob({
          id: 'j1',
          file_path: '/E01.mkv',
          status: 'processing',
          created_at: '2026-05-19T23:31:04.383Z',
        }),
      ],
      isConnected: true,
    })
    const { container } = renderWithRouter(
      <QueueList selectedId={null} onSelect={() => {}} />,
    )
    const rows = Array.from(container.querySelectorAll('[data-index]'))
    expect(rows[0]).toHaveTextContent('E01.mkv')
    expect(rows[1]).toHaveTextContent('E02.mkv')
    expect(rows[2]).toHaveTextContent('E03.mkv')
  })

  it('renders active jobs above terminal jobs; terminal sorted newest-first', () => {
    useJobStore.setState({
      jobs: [
        makeJob({
          id: 't_old',
          file_path: '/old-done.mkv',
          status: 'completed',
          created_at: '2026-05-19T10:00:00Z',
        }),
        makeJob({
          id: 'a_running',
          file_path: '/running.mkv',
          status: 'processing',
          created_at: '2026-05-19T20:00:00Z',
        }),
        makeJob({
          id: 't_new',
          file_path: '/new-done.mkv',
          status: 'completed',
          created_at: '2026-05-19T15:00:00Z',
        }),
      ],
      isConnected: true,
    })
    const { container } = renderWithRouter(
      <QueueList selectedId={null} onSelect={() => {}} />,
    )
    const rows = Array.from(container.querySelectorAll('[data-index]'))
    expect(rows[0]).toHaveTextContent('running.mkv')
    expect(rows[1]).toHaveTextContent('new-done.mkv')
    expect(rows[2]).toHaveTextContent('old-done.mkv')
  })

  it('positions virtual rows at virtualizer-computed offsets', () => {
    useJobStore.setState({
      jobs: [
        makeJob({ id: 'j1', file_path: '/media/A.mkv' }),
        makeJob({ id: 'j2', file_path: '/media/B.mkv' }),
        makeJob({ id: 'j3', file_path: '/media/C.mkv' }),
      ],
      isConnected: true,
    })
    const { container } = renderWithRouter(<QueueList selectedId={null} onSelect={() => {}} />)
    const rows = container.querySelectorAll('[data-index]')
    expect(rows).toHaveLength(3)
    expect((rows[0] as HTMLElement).style.transform).toBe('translateY(0px)')
    expect((rows[1] as HTMLElement).style.transform).toBe('translateY(110px)')
    expect((rows[2] as HTMLElement).style.transform).toBe('translateY(220px)')
  })
})
