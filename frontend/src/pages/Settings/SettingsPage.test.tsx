import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { apiFetch } from '@/lib/api'
import { routes } from '@/App'
import { baseMockSettings } from '@/test-utils/mockSettings'

// SettingsPage is the thin routing shell (`/settings/:section`) that delegates
// to SettingsLayout, which renders the active pane from a typed map. The
// per-pane behaviour lives in each *Pane.test.tsx — these tests only assert
// the routing → pane mapping, the rail, and the unsaved-changes contract.
//
// The route tree mounts SettingsPage via React.lazy + Suspense (see App.tsx).
// Under full-suite CPU contention the lazy chunk + useQuery resolution can
// exceed RTL's default 1000ms findBy window, so the route assertions use an
// explicit longer timeout.
const FIND = { timeout: 4000 } as const
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

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
      <Toaster />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
  vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
})

describe('SettingsPage routing', () => {
  it('renders the settings rail and the Jellyfin pane at /settings/jellyfin', async () => {
    renderAt('/settings/jellyfin')
    expect(
      await screen.findByRole('navigation', { name: /settings sections/i }, FIND),
    ).toBeInTheDocument()
    expect(await screen.findByTestId('pane-jellyfin', {}, FIND)).toBeInTheDocument()
  })

  it('renders the Saved Configurations pane at /settings/saved-configurations', async () => {
    renderAt('/settings/saved-configurations')
    expect(
      await screen.findByTestId('pane-saved-configurations', {}, FIND),
    ).toBeInTheDocument()
  })

  it('redirects /settings to the default Media Library pane', async () => {
    renderAt('/settings')
    expect(await screen.findByTestId('pane-media', {}, FIND)).toBeInTheDocument()
  })

  it('redirects an unknown section to the default Media Library pane', async () => {
    renderAt('/settings/bogus')
    expect(await screen.findByTestId('pane-media', {}, FIND)).toBeInTheDocument()
  })
})

describe('SettingsPage unsaved-changes bar', () => {
  it('is absent on mount for a dirty-capable pane', async () => {
    renderAt('/settings/jellyfin')
    await screen.findByTestId('pane-jellyfin', {}, FIND)
    expect(
      screen.queryByRole('region', { name: /unsaved changes/i }),
    ).not.toBeInTheDocument()
  })

  it('appears after the Media Library pane reports a field edit', async () => {
    renderAt('/settings/media')
    await screen.findByTestId('pane-media', {}, FIND)
    expect(
      screen.queryByRole('region', { name: /unsaved changes/i }),
    ).not.toBeInTheDocument()
    const input = await screen.findByPlaceholderText('/media', {}, FIND)
    await userEvent.type(input, '/extra')
    expect(
      await screen.findByRole('region', { name: /unsaved changes/i }),
    ).toBeInTheDocument()
  })
})
