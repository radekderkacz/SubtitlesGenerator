import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/sonner'
import CompletionCard from './CompletionCard'
import { makeJob } from '@/test-utils/mockJob'
import { baseMockSettings } from '@/test-utils/mockSettings'
import { apiFetch, refreshJellyfin } from '@/lib/api'
import type { Job, Settings } from '@/types/api'

vi.mock('@/lib/api', async (orig) => {
  const actual = await orig<typeof import('@/lib/api')>()
  return {
    ...actual,
    apiFetch: vi.fn(),
    refreshJellyfin: vi.fn(),
  }
})

function renderWith(job: Job, settings: Settings = baseMockSettings) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(apiFetch).mockResolvedValue(settings)
  return render(
    <QueryClientProvider client={qc}>
      <CompletionCard job={job} />
      <Toaster />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset()
  vi.mocked(refreshJellyfin).mockReset()
})

describe('CompletionCard', () => {
  it('renders the computed SRT path with .{target_language}.srt suffix', () => {
    renderWith(
      makeJob({
        file_path: '/media/films/Film.mkv',
        target_language: 'en',
        source_language: 'fr',
        completed_at: '2026-04-29T12:22:14Z',
        created_at: '2026-04-29T12:00:00Z',
      }),
    )
    expect(screen.getByText('/media/films/Film.en.srt')).toBeInTheDocument()
  })

  it('strips the original extension before appending .{lang}.srt', () => {
    renderWith(
      makeJob({ file_path: '/media/films/Film.with.dots.mkv', target_language: 'en' }),
    )
    expect(screen.getByText('/media/films/Film.with.dots.en.srt')).toBeInTheDocument()
  })

  it('falls back to a notice when target_language is missing', () => {
    renderWith(makeJob({ target_language: null }))
    expect(screen.getByText(/SRT path unavailable/)).toBeInTheDocument()
  })

  it('shows detected language and model', () => {
    renderWith(
      makeJob({ source_language: 'fr', target_language: 'en', model_size: 'large-v3' }),
    )
    expect(screen.getByText('fr')).toBeInTheDocument()
    expect(screen.getByText('large-v3')).toBeInTheDocument()
  })

  it('shows "system default" when model_size is null', () => {
    renderWith(makeJob({ model_size: null }))
    expect(screen.getByText('system default')).toBeInTheDocument()
  })

  it('shows the elapsed duration created_at → completed_at via formatDuration', () => {
    renderWith(
      makeJob({
        created_at: '2026-04-29T12:00:00Z',
        completed_at: '2026-04-29T12:22:14Z',
        target_language: 'en',
      }),
    )
    expect(screen.getByText('22m 14s')).toBeInTheDocument()
  })

  it('shows em-dash when completed_at is missing', () => {
    renderWith(makeJob({ completed_at: null }))
    const dts = screen.getAllByText('—')
    expect(dts.length).toBeGreaterThanOrEqual(1)
  })

  it('copies the SRT path to clipboard when the copy icon is clicked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    renderWith(makeJob({ file_path: '/media/Film.mkv', target_language: 'en' }))
    fireEvent.click(screen.getByRole('button', { name: 'Copy SRT path' }))
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('/media/Film.en.srt'))
  })

  // ---------------------------------------------------------------------------
  // Jellyfin status section
  // ---------------------------------------------------------------------------

  it('omits the Jellyfin section entirely when Jellyfin is not configured', async () => {
    renderWith(
      makeJob({ target_language: 'en' }),
      { ...baseMockSettings, jellyfin_url: null, jellyfin_api_key: null },
    )
    // Wait for the settings query to settle
    await waitFor(() => expect(apiFetch).toHaveBeenCalled())
    expect(screen.queryByLabelText('Jellyfin status')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open in Jellyfin/ })).not.toBeInTheDocument()
  })

  it('shows "Library refreshed ✓" when jellyfin_refreshed_at is set', async () => {
    renderWith(
      makeJob({
        target_language: 'en',
        jellyfin_refreshed_at: '2026-04-29T12:30:00Z',
      }),
      { ...baseMockSettings, jellyfin_url: 'http://jf.local', jellyfin_api_key: 'sk' },
    )
    expect(await screen.findByText(/Library refreshed/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Refresh Now/ })).not.toBeInTheDocument()
  })

  it('shows "Refresh pending" + Refresh Now button when not yet refreshed', async () => {
    renderWith(
      makeJob({ target_language: 'en', jellyfin_refreshed_at: null }),
      { ...baseMockSettings, jellyfin_url: 'http://jf.local', jellyfin_api_key: 'sk' },
    )
    expect(await screen.findByText(/Refresh pending/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Refresh Now/ })).toBeInTheDocument()
  })

  it('clicking Refresh Now calls refreshJellyfin', async () => {
    const updated = makeJob({
      target_language: 'en',
      jellyfin_refreshed_at: '2026-04-29T12:35:00Z',
    })
    vi.mocked(refreshJellyfin).mockResolvedValue(updated)
    renderWith(
      makeJob({ id: updated.id, target_language: 'en', jellyfin_refreshed_at: null }),
      { ...baseMockSettings, jellyfin_url: 'http://jf.local', jellyfin_api_key: 'sk' },
    )
    fireEvent.click(await screen.findByRole('button', { name: /Refresh Now/ }))
    await waitFor(() => expect(refreshJellyfin).toHaveBeenCalledWith(updated.id))
  })

  it('renders the Open in Jellyfin link to the configured Jellyfin URL', async () => {
    renderWith(
      makeJob({ target_language: 'en' }),
      { ...baseMockSettings, jellyfin_url: 'http://jf.local', jellyfin_api_key: 'sk' },
    )
    const link = await screen.findByRole('link', { name: /Open in Jellyfin/ })
    expect(link).toHaveAttribute('href', 'http://jf.local')
    expect(link).toHaveAttribute('target', '_blank')
  })
})
