import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BatchActionBar from './BatchActionBar'
import type { FileBrowseEntry, Settings } from '@/types/api'

// Spy on useNavigate so we can assert post-submit routing (bug #84).
// Spread the actual module so MemoryRouter etc. still resolve normally.
const mockNavigate = vi.fn()
vi.mock('react-router', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('react-router')>()
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  submitJob: vi.fn(),
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

vi.mock('@/lib/apiToast', () => ({
  withApiToast: vi.fn(async (fn: () => Promise<unknown>) => {
    await fn()
    return true
  }),
}))

const BASE_SETTINGS: Settings = {
  id: 1,
  nas_mount_path: '/mnt/nas',
  jellyfin_url: null,
  jellyfin_api_key: null,
  transcription_api_url: null,
  transcription_model: null,
  transcription_api_key: null,
  translation_provider: null,
  translation_model: null,
  translation_api_key: null,
  translation_api_url: null,
  hf_token: null,
  watch_folders: [],
  profiles: [{ name: 'gemma' }, { name: 'groq' }],
  prefer_existing_subs: true,
  created_at: '2026-04-29T00:00:00Z',
  updated_at: '2026-04-29T00:00:00Z',
}

const FILE_INDEX = new Map<string, FileBrowseEntry>([
  [
    '/a.mkv',
    {
      name: 'a.mkv',
      size_bytes: 1,
      modified_at: '2026-04-30T10:00:00Z',
      has_srt: true,
    },
  ],
  [
    '/b.mkv',
    {
      name: 'b.mkv',
      size_bytes: 1,
      modified_at: '2026-04-30T10:00:00Z',
      has_srt: false,
    },
  ],
])

function renderBar(onCleared = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BatchActionBar
          selectedPaths={['/a.mkv', '/b.mkv']}
          fileIndex={FILE_INDEX as never}
          onCleared={onCleared}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function pickProfile() {
  const trigger = await screen.findByRole('combobox')
  fireEvent.click(trigger)
  fireEvent.click(await screen.findByText('gemma'))
}

describe('BatchActionBar', () => {
  beforeEach(async () => {
    mockNavigate.mockReset()
    const { apiFetch, submitJob } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({ ...BASE_SETTINGS })
    vi.mocked(submitJob)
      .mockReset()
      .mockResolvedValue({ id: 'x', status: 'queued', created_at: '' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('skip-existing defaults OFF — submits one job per selected path', async () => {
    const { submitJob } = await import('@/lib/api')
    renderBar()
    await pickProfile()

    fireEvent.click(screen.getByRole('button', { name: /^Submit/ }))

    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledTimes(2),
    )
    const calls = vi.mocked(submitJob).mock.calls
    expect(new Set(calls.map((c) => c[0].file_path))).toEqual(
      new Set(['/a.mkv', '/b.mkv']),
    )
  })

  it('skip ON shows the skipped filename and submits only the eligible path', async () => {
    const { submitJob } = await import('@/lib/api')
    renderBar()
    await pickProfile()

    fireEvent.click(screen.getByLabelText(/Skip files with SRT/i))

    // The skipped file basename must be visible in the prominent list,
    // not just a count.
    expect(await screen.findByText('a.mkv')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^Submit/ }))

    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledTimes(1),
    )
    expect(vi.mocked(submitJob).mock.calls[0][0].file_path).toBe('/b.mkv')
  })

  // Generous timeout: this spec renders the full bar + profile picker and
  // has timed out at the default 5s on a loaded CI runner (2026-07-13).
  it('carries translate + target language per file (skip OFF)', { timeout: 20000 }, async () => {
    const { submitJob } = await import('@/lib/api')
    renderBar()
    await pickProfile()

    fireEvent.click(
      screen.getByRole('switch', { name: /Translate Subtitles/i }),
    )
    const lists = await screen.findAllByRole('list', {
      name: 'Language options',
    })
    // Source list is rendered first; target is the second.
    fireEvent.click(
      within(lists[1]).getByRole('button', { name: /Polish/i }),
    )

    fireEvent.click(screen.getByRole('button', { name: /^Submit/ }))

    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledTimes(2),
    )
    const calls = vi.mocked(submitJob).mock.calls
    for (const [arg] of calls) {
      expect(arg).toMatchObject({
        translate: true,
        target_language: 'pl',
        source_language: 'auto',
        profile_name: 'gemma',
      })
    }
    expect(new Set(calls.map((c) => c[0].file_path))).toEqual(
      new Set(['/a.mkv', '/b.mkv']),
    )
  })

  it('disables Submit when no profile is selected', async () => {
    renderBar()
    // Wait for the profile control to render (settings query resolved).
    await screen.findByRole('combobox')
    expect(screen.getByRole('button', { name: /^Submit/ })).toBeDisabled()
  })

  it('navigates to "/" (Active Queue) after a successful batch submit (bug #84)', async () => {
    const { submitJob } = await import('@/lib/api')
    renderBar()
    await pickProfile()
    fireEvent.click(screen.getByRole('button', { name: /^Submit/ }))
    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledTimes(2),
    )
    // After submit the user should land on the queue, not be stuck on /browse.
    await vi.waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/'))
  })

  it('does NOT navigate when every submission fails — user stays on Library to retry', async () => {
    // Force every per-file submit to be reported as a failure by withApiToast.
    const { withApiToast } = await import('@/lib/apiToast')
    vi.mocked(withApiToast).mockImplementation(async () => false)
    renderBar()
    await pickProfile()
    fireEvent.click(screen.getByRole('button', { name: /^Submit/ }))
    // Settle the async loop, then assert no navigation.
    await new Promise((r) => setTimeout(r, 50))
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('selection-reset button is labelled "Clear" (not "Cancel") to avoid sounding like a job-cancel (bug #85)', async () => {
    renderBar()
    // Wait for the bar to render (settings query resolved).
    await screen.findByRole('combobox')
    // No button labelled exactly "Cancel"; the selection-reset is "Clear".
    expect(
      screen.queryByRole('button', { name: /^Cancel$/i }),
    ).toBeNull()
    expect(
      screen.getByRole('button', { name: /^Clear$/i }),
    ).toBeInTheDocument()
  })
})
