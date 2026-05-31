import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { Toaster } from '@/components/ui/sonner'
import { apiFetch } from '@/lib/api'
import { baseMockSettings } from '@/test-utils/mockSettings'
import NasPathsPane from './NasPathsPane'

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
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        {children}
        <Toaster />
      </QueryClientProvider>
    </MemoryRouter>
  )
}

function renderPane(onDirtyChange = vi.fn()) {
  return render(<NasPathsPane onDirtyChange={onDirtyChange} />, { wrapper })
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
})

describe('NasPathsPane', () => {
  it('renders the pane root testid', async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    expect(screen.getByTestId('pane-media')).toBeInTheDocument()
  })

  it('renders the SectionHeader with title "Media Library"', async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    expect(screen.getByRole('heading', { name: 'Media Library' })).toBeInTheDocument()
  })

  it('loads the nas_mount_path from settings into the Media Root input', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseMockSettings,
      nas_mount_path: '/mnt/nas',
    })
    renderPane()
    await waitFor(() => {
      const input = screen.getByPlaceholderText('/media')
      expect(input).toHaveValue('/mnt/nas')
    })
  })

  it('calls apiFetch PUT to /api/v1/settings on Save', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
      .mockResolvedValueOnce({ status: 'ok' })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('/media')).toHaveValue('/mnt/nas')
    })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('shows "Settings saved" toast on successful save', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
      .mockResolvedValueOnce({ status: 'ok' })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('/media')).toHaveValue('/mnt/nas')
    })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Settings saved')).toBeInTheDocument()
  })

  it('calls onDirtyChange(true) when the path field is changed', async () => {
    const onDirtyChange = vi.fn()
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
    renderPane(onDirtyChange)
    const input = await screen.findByPlaceholderText('/media')
    await userEvent.type(input, '/extra')
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(true))
  })

  it('dispatches settings:save for nas-paths and triggers PUT', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
      .mockResolvedValueOnce({ status: 'ok' })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('/media')).toHaveValue('/mnt/nas')
    })
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'media' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('renders a link to /automations for watch folders', async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseMockSettings)
    renderPane()
    const link = await screen.findByRole('link', { name: /automations/i })
    expect(link).toHaveAttribute('href', '/automations')
  })

  it('ignores settings:save events for other sections', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...baseMockSettings, nas_mount_path: '/mnt/nas' })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('/media')).toHaveValue('/mnt/nas')
    })
    const callsBefore = vi.mocked(apiFetch).mock.calls.length
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'jellyfin' }))
    await new Promise((r) => setTimeout(r, 50))
    expect(vi.mocked(apiFetch).mock.calls.length).toBe(callsBefore)
  })
})
