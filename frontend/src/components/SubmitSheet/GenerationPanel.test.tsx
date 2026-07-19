import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import GenerationPanel from './GenerationPanel'
import type { FileBrowseEntry, Settings } from '@/types/api'

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

const mkFile = (overrides: Partial<FileBrowseEntry> = {}): FileBrowseEntry => ({
  name: 'Film.mkv',
  size_bytes: 8_000_000_000,
  modified_at: '2026-04-30T10:00:00Z',
  has_srt: false,
  ...overrides,
})

const BASE_SETTINGS: Settings = {
  id: 1,
  nas_mount_path: '/media',
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
  profiles: [{ name: 'Default' }] as unknown as Settings['profiles'],
  prefer_existing_subs: true,
  created_at: '2026-04-29T00:00:00Z',
  updated_at: '2026-04-29T00:00:00Z',
}

function renderPanel(props: { file?: FileBrowseEntry | null; fullPath?: string | null } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/browse',
        element: (
          <GenerationPanel
            file={props.file ?? mkFile()}
            fullPath={props.fullPath ?? '/media/films/Film.mkv'}
          />
        ),
      },
      { path: '/', element: <div>Queue</div> },
      { path: '/settings', element: <div>Settings</div> },
    ],
    { initialEntries: ['/browse'] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <Toaster />
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('GenerationPanel', () => {
  beforeEach(async () => {
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({ ...BASE_SETTINGS })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the Generate Subtitles CTA when a file is selected', async () => {
    renderPanel({ file: mkFile({ has_srt: false }) })
    expect(await screen.findByRole('button', { name: 'Generate Subtitles' })).toBeInTheDocument()
  })

  it('places the Generate button under the profile control, not in a bottom footer', async () => {
    renderPanel({ file: mkFile() })
    const button = await screen.findByRole('button', { name: 'Generate Subtitles' })
    // The button must sit inline beneath the controls — not pinned in a
    // separate <footer> at the bottom of the panel (the reported bug).
    expect(button.closest('footer')).toBeNull()
    // ...and it must come AFTER the AI Profile control in document order.
    const profileLabel = screen.getByText('AI Profile')
    expect(
      profileLabel.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })
})
