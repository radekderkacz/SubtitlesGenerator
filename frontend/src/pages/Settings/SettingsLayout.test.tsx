import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { baseMockSettings } from '@/test-utils/mockSettings'
import SettingsLayout from './SettingsLayout'

// SettingsLayout now renders the real panes (SP4-T14): each calls
// useQuery(['settings']) so the layout needs a QueryClientProvider and a
// mocked apiFetch. Dirtiness is driven through the real NasPathsPane field
// instead of the removed StubPane "make-dirty" button.
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

const r = (s = 'media') => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/settings/${s}`]}>
        <SettingsLayout section={s as never} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
  vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
})

describe('SettingsLayout', () => {
  it('renders the rail and the active section pane', async () => {
    r('jellyfin')
    expect(screen.getByRole('navigation', { name: /settings sections/i })).toBeInTheDocument()
    expect(await screen.findByTestId('pane-jellyfin')).toBeInTheDocument()
  })
  it('hides the unsaved bar until a pane reports dirty', async () => {
    r()
    expect(screen.queryByRole('region', { name: /unsaved changes/i })).not.toBeInTheDocument()
    const input = await screen.findByPlaceholderText('/media')
    await userEvent.type(input, '/extra')
    expect(
      await screen.findByRole('region', { name: /unsaved changes/i }),
    ).toBeInTheDocument()
  })
})
