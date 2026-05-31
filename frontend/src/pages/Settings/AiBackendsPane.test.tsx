import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import { apiFetch } from '@/lib/api'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'
import { baseMockSettings } from '@/test-utils/mockSettings'
import AiBackendsPane from './AiBackendsPane'

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

const aiSettings = {
  ...baseMockSettings,
  translation_provider: 'ollama',
  translation_api_url: 'http://ollama.local:11434',
  translation_model: 'llama3',
}

/**
 * Route mocked apiFetch by URL so the settings query, the on-visit
 * auto-probe (bodyless GET /api/v1/settings/transcription/health via
 * useSectionStatus, testing PERSISTED settings) and the explicit
 * Test-Connection / Refresh-models calls all resolve deterministically
 * regardless of order. `probeOk` controls ONLY the explicit
 * /test-transcription POST; the on-visit /transcription/health GET
 * always returns a benign ok so existing tests' on-mount pill state is
 * deterministic and each test exercises the explicit Test override.
 */
function mockApi(opts: {
  settings?: typeof aiSettings
  probeOk?: boolean
  probeReject?: boolean
  models?: string[]
} = {}) {
  const settings = opts.settings ?? aiSettings
  vi.mocked(apiFetch).mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/settings' && (!init || init.method !== 'PUT')) {
      return Promise.resolve(settings) as never
    }
    if (url === '/api/v1/settings' && init?.method === 'PUT') {
      return Promise.resolve({ status: 'ok' }) as never
    }
    if (url === '/api/v1/settings/transcription/health') {
      // On-visit bodyless GET health probe (persisted settings). Benign
      // by default — individual tests assert the explicit-Test override.
      return Promise.resolve({ ok: true, detail: '' }) as never
    }
    if (url === '/api/v1/settings/test-transcription') {
      if (opts.probeReject) return Promise.reject(new Error('whisper down')) as never
      const ok = opts.probeOk ?? true
      // The explicit Test handler reads `ok`/`detail` from this POST.
      return Promise.resolve({
        ok,
        detail: ok ? 'Ready — CPU' : 'Auth failed',
      }) as never
    }
    if (url === '/api/v1/settings/test-translation') {
      return Promise.resolve({ ok: true, detail: 'Connected' }) as never
    }
    if (url === '/api/v1/settings/list-translation-models') {
      return Promise.resolve({
        models: opts.models ?? ['gemma3', 'mistral'],
        detail: null,
      }) as never
    }
    return Promise.resolve({}) as never
  })
}

function renderPane(onDirtyChange = vi.fn()) {
  return render(<AiBackendsPane onDirtyChange={onDirtyChange} />, { wrapper })
}

beforeEach(() => {
  useSettingsStatusStore.setState({ byId: {} })
  vi.mocked(apiFetch).mockReset()
})

describe('AiBackendsPane', () => {
  it('renders the pane root testid', async () => {
    mockApi()
    renderPane()
    expect(screen.getByTestId('pane-ai-backends')).toBeInTheDocument()
  })

  it('renders the SectionHeader with title "AI Backends"', async () => {
    mockApi()
    renderPane()
    expect(screen.getByRole('heading', { name: 'AI Backends' })).toBeInTheDocument()
  })

  it('on-visit health probe drives the SectionHeader pill to ok on mount', async () => {
    // useSectionStatus auto-probes the bodyless GET
    // /api/v1/settings/transcription/health (persisted DB settings) on
    // mount — no Test click. { ok:true, detail:'Ready' } must reach the
    // SectionHeader pill: data-status 'ok' AND the detail string rendered
    // next to the dot (proving the probe's response — not just *some* ok —
    // reached the pill).
    vi.mocked(apiFetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/v1/settings' && (!init || init.method !== 'PUT')) {
        return Promise.resolve(aiSettings) as never
      }
      if (url === '/api/v1/settings/transcription/health') {
        expect(init?.body).toBeUndefined()
        expect(init?.method ?? 'GET').toBe('GET')
        return Promise.resolve({ ok: true, detail: 'Ready' }) as never
      }
      return Promise.resolve({}) as never
    })
    renderPane()
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
    // The detail renders inside the pill span that wraps section-status.
    const pill = screen.getByTestId('section-status').parentElement
    expect(pill).toHaveTextContent('Ready')
  })

  it('renders the Transcription and Translation engine sections', async () => {
    mockApi()
    renderPane()
    expect(await screen.findByText('Transcription Engine')).toBeInTheDocument()
    expect(screen.getByText('Translation Engine')).toBeInTheDocument()
  })

  it('loads transcription + translation fields from settings', async () => {
    mockApi()
    renderPane()
    // Translation provider seeded to ollama → Base URL + model fields render.
    expect(await screen.findByDisplayValue('llama3')).toBeInTheDocument()
    expect(screen.getByDisplayValue('http://ollama.local:11434')).toBeInTheDocument()
  })

  it('does NOT render the Profiles / Saved configurations section', async () => {
    mockApi()
    renderPane()
    await screen.findByText('Transcription Engine')
    expect(screen.queryByText(/Saved backend configurations/i)).not.toBeInTheDocument()
  })

  it('Refresh models POSTs to /api/v1/settings/list-translation-models', async () => {
    mockApi({ models: ['gemma3:27b'] })
    renderPane()
    await screen.findByDisplayValue('llama3')
    await userEvent.click(screen.getByRole('button', { name: /Refresh available models/i }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings/list-translation-models',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('transcription Test Connection POSTs test-transcription and shows the badge detail', async () => {
    mockApi({ probeOk: true })
    renderPane()
    // Wait for the settings query to hydrate (form.reset) before clicking —
    // a late reset changes watched fields and the effect would clear the
    // connectivity badge mid-assertion.
    await screen.findByDisplayValue('llama3')
    const testButtons = screen.getAllByRole('button', { name: /Test Connection/i })
    await userEvent.click(testButtons[0])
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings/test-transcription',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    // 'Ready — CPU' is the explicit /test-transcription detail. It appears
    // in the ConnectivityBadge and (via the Test handler's status-store
    // set) the SectionHeader pill — the on-visit health probe returns an
    // empty detail, so this string can only come from the explicit Test.
    // Assert at least one occurrence is present.
    expect((await screen.findAllByText('Ready — CPU')).length).toBeGreaterThan(0)
  })

  it('translation Test Connection POSTs test-translation and shows the badge detail', async () => {
    mockApi()
    renderPane()
    await screen.findByDisplayValue('llama3')
    const testButtons = screen.getAllByRole('button', { name: /Test Connection/i })
    await userEvent.click(testButtons[1])
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings/test-translation',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    expect(await screen.findByText('Connected')).toBeInTheDocument()
  })

  it('transcription Test Connection drives the section-status data-status to ok', async () => {
    mockApi({ probeOk: true })
    renderPane()
    await screen.findByText('Transcription Engine')
    const testButtons = screen.getAllByRole('button', { name: /Test Connection/i })
    await userEvent.click(testButtons[0])
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
  })

  it('transcription Test Connection failure drives the section-status to error', async () => {
    // Only /test-transcription rejects; the on-visit /transcription/health
    // probe is still benign (ok). Wait for the auto-probe to settle the
    // pill to 'ok' first so the later Test rejection deterministically
    // overrides it (an in-flight auto-probe can't clobber 'error' → 'ok').
    mockApi({ probeReject: true })
    renderPane()
    await screen.findByText('Transcription Engine')
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
    })
    const testButtons = screen.getAllByRole('button', { name: /Test Connection/i })
    await userEvent.click(testButtons[0])
    await waitFor(() => {
      expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'error')
    })
  })

  it('Save Changes calls PUT /api/v1/settings', async () => {
    mockApi()
    renderPane()
    await screen.findByText('Transcription Engine')
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('dispatches settings:save for ai-backends and triggers PUT', async () => {
    mockApi()
    renderPane()
    await screen.findByText('Transcription Engine')
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'ai-backends' }))
    await waitFor(() => {
      expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
        '/api/v1/settings',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
  })

  it('ignores settings:save events for other sections', async () => {
    mockApi()
    renderPane()
    await screen.findByText('Transcription Engine')
    const putBefore = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([url, init]) => url === '/api/v1/settings' && (init as RequestInit)?.method === 'PUT',
      ).length
    globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: 'jellyfin' }))
    await new Promise((r) => setTimeout(r, 50))
    const putAfter = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([url, init]) => url === '/api/v1/settings' && (init as RequestInit)?.method === 'PUT',
      ).length
    expect(putAfter).toBe(putBefore)
  })

  it('passes a vi.fn() onDirtyChange (no crash on mount)', async () => {
    const onDirtyChange = vi.fn()
    mockApi()
    renderPane(onDirtyChange)
    await screen.findByText('Transcription Engine')
    expect(onDirtyChange).toHaveBeenCalled()
  })
})
