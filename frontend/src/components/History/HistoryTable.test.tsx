import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router'
import HistoryTable from './HistoryTable'
import type { HistoryEntry } from '@/types/api'

vi.mock('@/lib/api', () => ({
  regenerateJob: vi.fn(),
}))

vi.mock('@/lib/apiToast', () => ({
  withApiToast: vi.fn((fn: () => Promise<unknown>) => fn()),
}))

function makeEntry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  const created = '2026-04-24T09:14:00Z'
  return {
    id: 'job-1',
    status: 'completed',
    file_path: '/mnt/nas/films/Foo.mkv',
    source_language: 'fr',
    target_language: 'en',
    model_size: 'large-v3',
    translation_provider: null,
    translation_model: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    cost_usd: null,
    srt_path: '/mnt/nas/films/Foo.en.srt',
    source_srt_path: null,
    error_message: null,
    created_at: created,
    updated_at: '2026-04-24T09:36:00Z',
    completed_at: '2026-04-24T09:36:00Z',
    jellyfin_refreshed_at: null,
    verification_status: null,
    verification_score: null,
    ...overrides,
  }
}

function renderWithRouter(entries: HistoryEntry[]) {
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <>
            <HistoryTable entries={entries} onDelete={vi.fn()} />
            <LocationProbe />
          </>
        ),
      },
      {
        path: '/jobs/:id',
        element: <LocationProbe />,
      },
    ],
    { initialEntries: ['/'] },
  )
  return render(<RouterProvider router={router} />)
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="route">{location.pathname}</div>
}

beforeEach(() => {
  // jsdom doesn't ship a real clipboard; provide a writable stub per test.
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  })
})

describe('HistoryTable', () => {
  it('renders the AC1 columns in the header', () => {
    renderWithRouter([])
    for (const header of ['Filename', 'Status', 'Language', 'Model', 'SRT', 'Duration', 'Completed',
      'Provider', 'Tokens', 'Cost']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument()
    }
  })

  it('renders a populated row with all the expected fields', () => {
    renderWithRouter([makeEntry()])
    expect(screen.getByText('Foo.mkv')).toBeInTheDocument()
    expect(screen.getByLabelText('Status: Done')).toBeInTheDocument()
    expect(screen.getByText('en')).toBeInTheDocument()
    expect(screen.getByText('large-v3')).toBeInTheDocument()
    // SRT path renders the basename (full path lives in the title attribute)
    expect(screen.getByText('Foo.en.srt')).toBeInTheDocument()
  })

  it('renders the verification badge when the entry has a verdict', () => {
    renderWithRouter([makeEntry({ verification_status: 'pass', verification_score: 95 })])
    expect(screen.getByText('Looks good')).toBeInTheDocument()
  })

  it('shows — for SRT path when the entry has none', () => {
    const failedEarly = makeEntry({ status: 'failed', srt_path: null, error_message: 'CUDA OOM' })
    renderWithRouter([failedEarly])
    expect(screen.queryByLabelText(/Copy SRT path/)).not.toBeInTheDocument()
  })

  it('failed row has the error message in its title attribute (AC4)', () => {
    const failed = makeEntry({ status: 'failed', error_message: 'CUDA OOM' })
    const { container } = renderWithRouter([failed])
    const row = container.querySelector('tr[title="CUDA OOM"]')
    expect(row).not.toBeNull()
  })

  it('clicking the SRT copy button writes the full path to clipboard and stops row navigation', async () => {
    renderWithRouter([makeEntry()])
    const copy = screen.getByLabelText(/Copy SRT path/)
    fireEvent.click(copy)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('/mnt/nas/films/Foo.en.srt')
    // Still on the table route; no navigation occurred.
    expect(screen.getByTestId('route').textContent).toBe('/')
  })

  it('clicking a row navigates to /jobs/:id (AC5)', () => {
    renderWithRouter([makeEntry({ id: 'abc-123' })])
    const row = screen.getByText('Foo.mkv').closest('tr')!
    fireEvent.click(row)
    expect(screen.getByTestId('route').textContent).toBe('/jobs/abc-123')
  })

  it('Regenerate button calls regenerateJob with the entry id', async () => {
    const { regenerateJob } = await import('@/lib/api')
    vi.mocked(regenerateJob).mockResolvedValue(undefined)
    renderWithRouter([makeEntry({ id: 'job-9' })])
    fireEvent.click(screen.getByLabelText(/regenerate/i))
    expect(regenerateJob).toHaveBeenCalledWith('job-9')
  })

  it('Regenerate button shows even when the row has no SRT (failed/cancelled)', () => {
    renderWithRouter([makeEntry({ id: 'job-x', status: 'failed', srt_path: null })])
    expect(screen.getByLabelText(/regenerate/i)).toBeInTheDocument()
  })

  it('renders provider, model, tokens and the three cost states', () => {
    const base: HistoryEntry = {
      id: 'j',
      status: 'completed',
      file_path: '/m/F.mkv',
      source_language: 'en',
      target_language: 'pl',
      model_size: 'large-v3',
      translation_provider: null,
      translation_model: null,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
      cost_usd: null,
      srt_path: null,
      source_srt_path: null,
      error_message: null,
      created_at: '2026-05-17T00:00:00Z',
      updated_at: '2026-05-17T00:10:00Z',
      completed_at: '2026-05-17T00:10:00Z',
      jellyfin_refreshed_at: null,
      verification_status: null,
      verification_score: null,
    }
    const rows: HistoryEntry[] = [
      { ...base, id: 'a', translation_provider: 'openrouter', translation_model: 'google/gemini-2.0-flash-001', prompt_tokens: 1000, completion_tokens: 500, total_tokens: 1500, cost_usd: 0.0123 },
      { ...base, id: 'b', translation_provider: 'ollama', translation_model: 'llama3', prompt_tokens: 600, completion_tokens: 300, total_tokens: 900, cost_usd: 0 },
      { ...base, id: 'c', translation_provider: 'openai', translation_model: 'gpt-4o', prompt_tokens: 400, completion_tokens: 300, total_tokens: 700, cost_usd: null },
    ]
    renderWithRouter(rows)
    expect(screen.getByText('openrouter')).toBeInTheDocument()
    expect(screen.getByText('google/gemini-2.0-flash-001')).toBeInTheDocument()
    expect(screen.getByText('1,500')).toBeInTheDocument()
    expect(screen.getByText('$0.0123')).toBeInTheDocument()
    expect(screen.getByText('$0.0000')).toBeInTheDocument()
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })
})

describe('provenance badge', () => {
  it('marks rows translated from an existing SRT', () => {
    renderWithRouter([makeEntry({ id: 'h1', source_srt_path: '/media/Film.en.srt' })])
    const badge = screen.getByLabelText(/Translated from existing subtitles: Film\.en\.srt/)
    expect(badge).toHaveTextContent('From SRT')
  })

  it('shows no badge for from-scratch generations', () => {
    renderWithRouter([makeEntry({ id: 'h2', source_srt_path: null })])
    expect(screen.queryByText('From SRT')).not.toBeInTheDocument()
  })
})
