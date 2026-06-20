import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import SubmitSheet from './SubmitSheet'
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
  profiles: null,
  created_at: '2026-04-29T00:00:00Z',
  updated_at: '2026-04-29T00:00:00Z',
}

function renderSheet(props: {
  open?: boolean
  file?: FileBrowseEntry | null
  fullPath?: string | null
  onOpenChange?: (open: boolean) => void
  settings?: Partial<Settings>
}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/browse',
        element: (
          <SubmitSheet
            open={props.open ?? true}
            onOpenChange={props.onOpenChange ?? (() => {})}
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
      {/* Toaster lives OUTSIDE the router so it survives the post-submit
          navigate('/') that would otherwise unmount the toast container
          before the test's waitFor sees it. */}
      <Toaster />
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('SubmitSheet', () => {
  beforeEach(async () => {
    const { apiFetch, submitJob } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({ ...BASE_SETTINGS })
    vi.mocked(submitJob).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the filename and SRT badge in the header', () => {
    renderSheet({ file: mkFile({ name: 'Seven.Samurai.1954.mkv', has_srt: false }) })
    expect(screen.getByText('Seven.Samurai.1954.mkv')).toBeInTheDocument()
    expect(screen.getByLabelText('No SRT')).toBeInTheDocument()
  })

  it('shows "Generate Subtitles" CTA when has_srt=false', () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    expect(screen.getByRole('button', { name: 'Generate Subtitles' })).toBeInTheDocument()
  })

  it('places the Generate button under the controls, not in the bottom footer', () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    const button = screen.getByRole('button', { name: 'Generate Subtitles' })
    // Consistent with GenerationPanel: inline beneath the controls, NOT pinned
    // in the SheetFooter at the bottom of the drawer.
    expect(button.closest('[data-slot="sheet-footer"]')).toBeNull()
    // It must share the scrollable content container with the AI Profile control.
    const scroll = screen.getByText('AI Profile').closest('.overflow-y-auto')
    expect(scroll).not.toBeNull()
    expect(scroll?.contains(button)).toBe(true)
  })

  it('shows "Regenerate" CTA when has_srt=true', () => {
    renderSheet({ file: mkFile({ has_srt: true }) })
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeInTheDocument()
  })

  it('opens the regenerate confirmation when Regenerate is clicked on an SRT-existing file', async () => {
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({
      ...BASE_SETTINGS,
      profiles: [{ name: 'p1' }],
    })
    renderSheet({ file: mkFile({ name: 'Film.mkv', has_srt: true }) })

    // Wait for profile dropdown to appear and select a profile (required for submit to be enabled)
    const trigger = await screen.findByRole('combobox')
    fireEvent.click(trigger)
    const option = await screen.findByText('p1')
    fireEvent.click(option)

    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    expect(
      await screen.findByText('Regenerate subtitles for Film.mkv?'),
    ).toBeInTheDocument()
  })

  it('shows an error toast and stays open when the submit API fails', async () => {
    const { apiFetch, submitJob, ApiRequestError } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({
      ...BASE_SETTINGS,
      profiles: [{ name: 'p1' }],
    })
    vi.mocked(submitJob).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Backend exploded'),
    )
    const onOpenChange = vi.fn()
    renderSheet({
      file: mkFile({ has_srt: false }),
      fullPath: '/media/films/Film.mkv',
      onOpenChange,
    })

    // Wait for profiles to load then pick one
    const trigger = await screen.findByRole('combobox')
    fireEvent.click(trigger)
    const option = await screen.findByText('p1')
    fireEvent.click(option)

    fireEvent.click(screen.getByRole('button', { name: 'Generate Subtitles' }))

    await vi.waitFor(() => expect(screen.getByText('Backend exploded')).toBeInTheDocument())
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it('disables the Translate switch and hides target language picker when Translate is off', () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    // Auto-detect text or label should be visible; no "Translate to" label yet
    expect(screen.queryByText(/Translate to/i)).not.toBeInTheDocument()
  })

  it('shows target language picker when Translate toggle is enabled', async () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    fireEvent.click(screen.getByRole('switch', { name: /Translate Subtitles/i }))
    expect(await screen.findByText(/Translate to/i)).toBeInTheDocument()
  })

  it('hides the Auto-detect language option from target and blocks submit when no real target is selected', async () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    fireEvent.click(screen.getByRole('switch', { name: /Translate Subtitles/i }))

    // The "Translate to" LanguageSelector has excludeAuto=true, so no "Auto-detect" in its list
    const lists = await screen.findAllByRole('list', { name: 'Language options' })
    // Second list is the target-language one (source is first)
    const targetList = lists[1]
    expect(targetList).not.toHaveTextContent('Auto-detect')

    // Inline explanation appears
    expect(
      screen.getByText(/Pick a specific target language/i),
    ).toBeInTheDocument()

    // CTA is disabled until they pick something
    const cta = screen.getByRole('button', { name: 'Generate Subtitles' })
    expect(cta).toBeDisabled()
  })

  // --- SP-2 new tests ---

  it('blocks submit and links to Profiles when no profiles exist', async () => {
    renderSheet({ file: mkFile({ has_srt: false }) })
    // With profiles: null (BASE_SETTINGS), the "No profiles yet" hint appears
    expect(await screen.findByText(/create one in Settings → Profiles/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate Subtitles' })).toBeDisabled()
  })

  it('submits source-only payload with chosen profile', async () => {
    const { apiFetch, submitJob } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({
      ...BASE_SETTINGS,
      profiles: [{ name: 'p1' }],
    })
    vi.mocked(submitJob).mockResolvedValue({
      id: 'job-1',
      status: 'queued',
      created_at: '2026-04-30T12:00:00Z',
    })
    const onOpenChange = vi.fn()
    renderSheet({
      file: mkFile({ has_srt: false }),
      fullPath: '/media/films/Film.mkv',
      onOpenChange,
    })

    // Wait for profile dropdown to appear then select p1
    const trigger = await screen.findByRole('combobox')
    fireEvent.click(trigger)
    const option = await screen.findByText('p1')
    fireEvent.click(option)

    fireEvent.click(screen.getByRole('button', { name: 'Generate Subtitles' }))

    await vi.waitFor(() =>
      expect(vi.mocked(submitJob)).toHaveBeenCalledWith(
        expect.objectContaining({
          file_path: '/media/films/Film.mkv',
          profile_name: 'p1',
          source_language: 'auto',
          translate: false,
        }),
      ),
    )
    // target_language must NOT be present (not just undefined — absent from object)
    const call = vi.mocked(submitJob).mock.calls[0][0]
    expect(Object.prototype.hasOwnProperty.call(call, 'target_language')).toBe(false)

    await vi.waitFor(() =>
      expect(
        screen.getByText('Processing continues even if you close this tab.'),
      ).toBeInTheDocument(),
    )
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('disables submit when translate on and target is auto/empty', async () => {
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue({
      ...BASE_SETTINGS,
      profiles: [{ name: 'p1' }],
    })
    renderSheet({ file: mkFile({ has_srt: false }) })

    // Wait for profiles to load, select one
    const trigger = await screen.findByRole('combobox')
    fireEvent.click(trigger)
    const option = await screen.findByText('p1')
    fireEvent.click(option)

    // Enable translate without picking a target
    fireEvent.click(screen.getByRole('switch', { name: /Translate Subtitles/i }))

    // CTA must remain disabled
    expect(screen.getByRole('button', { name: 'Generate Subtitles' })).toBeDisabled()
  })
})
