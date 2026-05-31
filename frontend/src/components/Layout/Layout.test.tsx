import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import Layout from './Layout'
import { useJobStore } from '@/store/jobStore'

vi.mock('@/hooks/useJobStream', () => ({
  useJobStream: vi.fn(),
}))

function renderWithRouter(initialPath = '/') {
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <Layout />,
        children: [
          { index: true, element: <div>content</div> },
          { path: 'browse', element: <div>browse</div> },
          { path: 'history', element: <div>history</div> },
          { path: 'settings', element: <div>settings</div> },
          { path: 'automations', element: <div>automations</div> },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  )
  return render(<RouterProvider router={router} />)
}

describe('Layout', () => {
  beforeEach(() => {
    // Ensure each test starts with a "fresh / connected" SSE state so the
    // ConnectionBanner (mounted in the shell) defaults to hidden — tests
    // that need to exercise the disconnected state set it explicitly.
    useJobStore.setState({
      jobs: [],
      isConnected: true,
      lastEventAt: Date.now(),
    })
  })

  it('renders the SubtitlesGen brand block in the sidebar', () => {
    renderWithRouter()
    expect(screen.getByText('SubtitlesGen')).toBeInTheDocument()
    expect(screen.getByText('by Derkos Labs')).toBeInTheDocument()
  })

  it('renders all five nav links including Library and Automations', () => {
    renderWithRouter()
    expect(screen.getByRole('link', { name: /queue/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /library/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /automations/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /history/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /settings/i })).toBeInTheDocument()
  })

  it('renders the SSE status indicator dot in the footer', () => {
    renderWithRouter()
    expect(screen.getByTestId('sse-status-dot')).toBeInTheDocument()
  })

  it('renders the New Task CTA at the bottom of the sidebar', () => {
    renderWithRouter()
    expect(
      screen.getByRole('button', { name: /new task/i }),
    ).toBeInTheDocument()
  })

  it('renders child route content via Outlet', () => {
    renderWithRouter()
    expect(screen.getByText('content')).toBeInTheDocument()
  })

  it('mounts ConnectionBanner in the shell so SSE staleness surfaces on every page', () => {
    // Hoisted from QueuePage to Layout so a disconnected SSE is visible on
    // /browse, /settings, /history, /jobs/:id — not just the queue.
    useJobStore.setState({ isConnected: false })
    renderWithRouter()
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument()
    // Sanity: it stays out of the way when the connection is fine.
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
  })

  it('keeps the banner hidden on the happy path (fresh connection)', () => {
    renderWithRouter()
    expect(screen.queryByTestId('connection-banner')).not.toBeInTheDocument()
  })

  // The banner was hoisted to Layout but the SSE connection (useJobStream)
  // still lived on QueuePage. Result: navigate away for >60s → banner
  // appears on every other page because lastEventAt never refreshes.
  // The hook must run wherever the banner does — the shell.
  it('subscribes to the job SSE stream so the banner has live data on every page', async () => {
    const { useJobStream } = await import('@/hooks/useJobStream')
    vi.mocked(useJobStream).mockClear()
    renderWithRouter()
    expect(vi.mocked(useJobStream)).toHaveBeenCalled()
  })
})
