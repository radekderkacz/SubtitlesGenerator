import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BatchPanel from './BatchPanel'
import type { FileBrowseEntry, Settings } from '@/types/api'

// Spy on useNavigate so we can assert post-submit routing.
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
      has_srt: false,
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

function renderPanel(onCleared = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BatchPanel
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

describe('BatchPanel', () => {
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

  it('submits one job per selected path and navigates to "/" on success', async () => {
    const { submitJob } = await import('@/lib/api')
    renderPanel()
    await pickProfile()

    fireEvent.click(screen.getByRole('button', { name: /generate/i }))

    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledTimes(2),
    )
    const calls = vi.mocked(submitJob).mock.calls
    expect(new Set(calls.map((c) => c[0].file_path))).toEqual(
      new Set(['/a.mkv', '/b.mkv']),
    )
    await vi.waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/'))
  })
})
