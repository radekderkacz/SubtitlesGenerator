import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { routes } from '@/App'
import { baseMockSettings } from '@/test-utils/mockSettings'

// The real Settings panes (wired into SettingsLayout in SP4-T14) each call
// useQuery(['settings']) on mount, so the route tree now needs a
// QueryClientProvider and a mocked apiFetch — without them the panes would
// throw "No QueryClient set". These tests still only assert route → pane.
vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
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

function at(path: string) {
  return createMemoryRouter(routes, { initialEntries: [path] })
}

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={at(path)} />
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  const { apiFetch } = await import('@/lib/api')
  vi.mocked(apiFetch).mockReset()
  vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
})

describe('settings routing', () => {
  it('redirects /settings to the default section', async () => {
    renderAt('/settings')
    expect(await screen.findByTestId('pane-media')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /settings sections/i })).toBeInTheDocument()
  })
  it('redirects an unknown section to the default', async () => {
    renderAt('/settings/bogus')
    expect(await screen.findByTestId('pane-media')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /settings sections/i })).toBeInTheDocument()
  })
  it('renders a valid section from the URL', async () => {
    renderAt('/settings/jellyfin')
    expect(await screen.findByTestId('pane-jellyfin')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: /settings sections/i })).toBeInTheDocument()
  })
})
