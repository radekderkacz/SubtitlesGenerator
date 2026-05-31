import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { apiFetch } from '@/lib/api'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'
import { baseMockSettings } from '@/test-utils/mockSettings'
import JellyfinPane from './JellyfinPane'

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

function renderPane(onDirtyChange = vi.fn()) {
  return render(<JellyfinPane onDirtyChange={onDirtyChange} />, { wrapper })
}

/**
 * Route mocked apiFetch by URL so the settings query, the on-visit
 * auto-probe (bodyless GET /api/v1/settings/jellyfin/health via
 * useSectionStatus, testing PERSISTED settings) and the explicit
 * Test-Connection POST (/test-jellyfin, testing the typed form values)
 * all resolve deterministically regardless of order.
 * `probeOk` controls ONLY what the explicit /test-jellyfin POST returns;
 * the on-visit /jellyfin/health GET always returns a benign ok so the
 * default pill state is deterministic and the Test override is what each
 * test exercises.
 */
function mockApi(opts: {
  settings?: typeof baseMockSettings
  probeOk?: boolean
  probeReject?: boolean
} = {}) {
  const settings = opts.settings ?? baseMockSettings
  vi.mocked(apiFetch).mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/settings' && (!init || init.method !== 'PUT')) {
      return Promise.resolve(settings) as never
    }
    if (url === '/api/v1/settings' && init?.method === 'PUT') {
      return Promise.resolve({ status: 'ok' }) as never
    }
    if (url === '/api/v1/settings/jellyfin/health') {
      // On-visit bodyless GET health probe (persisted settings). Benign
      // by default — individual tests assert the explicit-Test override.
      return Promise.resolve({ ok: true, detail: '' }) as never
    }
    if (url === '/api/v1/settings/test-jellyfin') {
      if (opts.probeReject) return Promise.reject(new Error('jellyfin down')) as never
      const ok = opts.probeOk ?? true
      // The Test handler reads `ok`/`detail` from the typed-values POST.
      return Promise.resolve({
        ok,
        detail: ok ? 'Connected' : 'Auth failed',
      }) as never
    }
    return Promise.resolve({}) as never
  })
}

beforeEach(() => {
  useSettingsStatusStore.setState({ byId: {} })
  vi.mocked(apiFetch).mockReset()
})

describe('JellyfinPane', () => {
  it('renders the pane root testid', async () => {
    mockApi()
    renderPane()
    expect(screen.getByTestId('pane-jellyfin')).toBeInTheDocument()
  })

  it('renders the SectionHeader with title "Jellyfin"', async () => {
    mockApi()
    renderPane()
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument()
  })

  it('loads jellyfin settings into the URL and API key fields', async () => {
    mockApi({
      settings: {
        ...baseMockSettings,
        jellyfin_url: 'http://jelly.local:8096',
        jellyfin_api_key: 'secret-key',
      },
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toHaveValue(
        'http://jelly.local:8096',
      )
    })
    expect(screen.getByPlaceholderText('Enter API key')).toHaveValue('secret-key')
  })

  it('Test Connection posts to /api/v1/settings/test-jellyfin and sets status pill to ok', async () => {
    mockApi({ probeOk: true })
    renderPane()
    // Suppress the auto-probe result first so we observe the explicit click.
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /Test Connection/ }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings/test-jellyfin',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
  })

  it('on-visit health drives the pill ok; the typed-values Test result overrides it (dual-model / SP-2-class guard)', async () => {
    // Two distinct calls drive the pill, and BOTH must work:
    //  1. On mount, useSectionStatus auto-probes the bodyless GET
    //     /jellyfin/health (persisted DB settings) → { ok:true } →
    //     pill becomes 'ok'.
    //  2. Clicking "Test Connection" POSTs /test-jellyfin WITH a body
    //     (the typed form values) → { ok:false } → pill must become
    //     'warn', overriding the on-visit result.
    // The two endpoints return DIFFERENT results on purpose: if the
    // on-visit probe were dropped the first assertion fails; if the Test
    // handler discarded the typed-values response (the SP-2-class bug)
    // the pill would stay 'ok' and the second assertion fails.
    vi.mocked(apiFetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/v1/settings' && (!init || init.method !== 'PUT')) {
        return Promise.resolve(baseMockSettings) as never
      }
      if (url === '/api/v1/settings/jellyfin/health') {
        // Bodyless GET, persisted settings → reachable.
        expect(init?.body).toBeUndefined()
        return Promise.resolve({ ok: true, detail: 'Connected' }) as never
      }
      if (url === '/api/v1/settings/test-jellyfin') {
        // POST WITH a body — the typed (possibly unsaved) form values.
        expect(init?.body).toBeDefined()
        return Promise.resolve({ ok: false, detail: 'Auth failed' }) as never
      }
      return Promise.resolve({}) as never
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toBeInTheDocument()
    })
    // Transition 1: on-visit health probe settles the pill to 'ok'.
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
    // Transition 2: explicit Test of the typed values overrides to 'warn'.
    await userEvent.click(screen.getByRole('button', { name: /Test Connection/ }))
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'warn')
    })
  })

  it('Test Connection failure drives the status pill to error', async () => {
    // Only /test-jellyfin rejects; the on-visit /jellyfin/health probe is
    // still benign (ok). Wait for the auto-probe to settle the pill to
    // 'ok' first so the later Test rejection deterministically overrides
    // it (and an in-flight auto-probe can't clobber 'error' back to 'ok').
    mockApi({ probeReject: true })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
    await userEvent.click(screen.getByRole('button', { name: /Test Connection/ }))
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'error')
    })
  })

  it('calls apiFetch PUT to /api/v1/settings on Save', async () => {
    mockApi({
      settings: { ...baseMockSettings, jellyfin_url: 'http://jelly.local:8096' },
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toHaveValue(
        'http://jelly.local:8096',
      )
    })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('dispatches settings:save for jellyfin and triggers PUT', async () => {
    mockApi({
      settings: { ...baseMockSettings, jellyfin_url: 'http://jelly.local:8096' },
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toHaveValue(
        'http://jelly.local:8096',
      )
    })
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'jellyfin' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('ignores settings:save events for other sections', async () => {
    mockApi({
      settings: { ...baseMockSettings, jellyfin_url: 'http://jelly.local:8096' },
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('http://jellyfin.local:8096')).toHaveValue(
        'http://jelly.local:8096',
      )
    })
    const putBefore = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([url, init]) => url === '/api/v1/settings' && (init as RequestInit)?.method === 'PUT',
      ).length
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'media' }))
    await new Promise((r) => setTimeout(r, 50))
    const putAfter = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([url, init]) => url === '/api/v1/settings' && (init as RequestInit)?.method === 'PUT',
      ).length
    expect(putAfter).toBe(putBefore)
  })
})
