import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { apiFetch } from '@/lib/api'
import { baseMockSettings } from '@/test-utils/mockSettings'
import SavedConfigurationsPane from './SavedConfigurationsPane'

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

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster />
    </QueryClientProvider>
  )
}

function renderPane() {
  return render(<SavedConfigurationsPane />, { wrapper })
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
})

describe('SavedConfigurationsPane', () => {
  it('renders the pane root testid', () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    expect(screen.getByTestId('pane-saved-configurations')).toBeInTheDocument()
  })

  it('renders the SectionHeader with title "Saved Configurations"', () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    expect(screen.getByRole('heading', { name: 'Saved Configurations' })).toBeInTheDocument()
  })

  it('renders empty-state message when there are no profiles', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, profiles: [] })
    renderPane()
    expect(await screen.findByText(/No profiles saved yet/)).toBeInTheDocument()
  })

  it('renders profiles loaded from settings', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      profiles: [
        { name: 'Homelab Local' },
        { name: 'OpenAI Paid', translation_provider: 'openai', translation_model: 'gpt-4o' },
      ],
    })
    renderPane()
    expect(await screen.findByText('Homelab Local')).toBeInTheDocument()
    expect(await screen.findByText('OpenAI Paid')).toBeInTheDocument()
  })

  it('calls apiFetch PUT /api/v1/settings with updated profiles on delete', async () => {
    const initialProfiles = [
      { name: 'Homelab Local' },
      { name: 'OpenAI Paid', translation_provider: 'openai' },
    ]
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ ...baseMockSettings, profiles: initialProfiles })
      .mockResolvedValueOnce({ status: 'ok' })
      .mockResolvedValueOnce({ ...baseMockSettings, profiles: [initialProfiles[1]] })

    renderPane()
    const deleteBtn = await screen.findByRole('button', { name: 'Delete profile Homelab Local' })
    await userEvent.click(deleteBtn)

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ profiles: [initialProfiles[1]] }),
        }),
      )
    })
  })

  it('saves a new profile snapshot when Save profile is clicked', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        ...baseMockSettings,
        profiles: [],
      })
      .mockResolvedValueOnce({ status: 'ok' })
      .mockResolvedValueOnce({ ...baseMockSettings, profiles: [{ name: 'My Setup' }] })

    renderPane()
    await screen.findByText(/No profiles saved yet/)

    const input = screen.getByPlaceholderText('Homelab Local')
    await userEvent.type(input, 'My Setup')

    const saveBtn = screen.getByRole('button', { name: /Save profile/ })
    await userEvent.click(saveBtn)

    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('does NOT listen for settings:save events', async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    await screen.findByText(/No profiles saved yet/)

    const callsBefore = vi.mocked(apiFetch).mock.calls.length
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'saved-configurations' }))
    await new Promise((r) => setTimeout(r, 50))
    // No additional calls: pane ignores the save event
    expect(vi.mocked(apiFetch).mock.calls.length).toBe(callsBefore)
  })
})
