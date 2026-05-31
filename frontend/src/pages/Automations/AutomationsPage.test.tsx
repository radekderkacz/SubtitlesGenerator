import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AutomationsPage from './AutomationsPage'

vi.mock('@/lib/api', () => ({
  listTriggers: vi.fn(),
  listTriggerEvents: vi.fn(),
  fireTrigger: vi.fn(),
  revealTriggerSecret: vi.fn(),
  deleteTrigger: vi.fn(),
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  apiFetch: vi.fn(),
}))

const { listTriggers, listTriggerEvents } = await import('@/lib/api')

const WATCH_TRIGGER = {
  id: 't1',
  name: 'Marshals TV',
  type: 'watch' as const,
  enabled: true,
  config: { path: '/shared/TV' },
  action: {
    profile_name: 'Default',
    source_language: null,
    target_language: null,
    skip_if_srt: true,
  },
  file_filter: { type: 'all' as const, value: null },
  fire_count_24h: 5,
  last_fired_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  vi.mocked(listTriggers).mockResolvedValue([])
  vi.mocked(listTriggerEvents).mockResolvedValue([])
})

const SECOND_TRIGGER = {
  ...WATCH_TRIGGER,
  id: 't2',
  name: 'Movies Library',
  config: { path: '/shared/Movies' },
}

describe('AutomationsPage', () => {
  it('renders page heading and New Trigger button', () => {
    render(<AutomationsPage />, { wrapper: wrapper() })
    expect(screen.getByText('Automations')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /new trigger/i })).toBeInTheDocument()
  })

  it('shows empty state when no triggers returned', async () => {
    render(<AutomationsPage />, { wrapper: wrapper() })
    await waitFor(() =>
      expect(screen.getByText(/no triggers yet/i)).toBeInTheDocument()
    )
  })

  it('renders trigger card when triggers are returned', async () => {
    vi.mocked(listTriggers).mockResolvedValue([WATCH_TRIGGER])
    render(<AutomationsPage />, { wrapper: wrapper() })
    await waitFor(() => expect(screen.getByText('Marshals TV')).toBeInTheDocument())
  })

  it('opens editor sheet when New Trigger is clicked', async () => {
    render(<AutomationsPage />, { wrapper: wrapper() })
    fireEvent.click(screen.getByRole('button', { name: /new trigger/i }))
    await waitFor(() =>
      expect(screen.getByText('New Trigger')).toBeInTheDocument()
    )
  })

  // Bug A — clicking Edit on a trigger must open the editor pre-filled
  // with that trigger's values. Previously the editor was always mounted at
  // page load with `trigger=undefined`, so `useState(trigger?.name ?? '')`
  // froze the name field empty regardless of subsequent prop changes.
  it('Edit on a trigger populates the form with that trigger\'s values', async () => {
    vi.mocked(listTriggers).mockResolvedValue([WATCH_TRIGGER])
    render(<AutomationsPage />, { wrapper: wrapper() })
    await screen.findByText('Marshals TV')

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    await screen.findByRole('heading', { name: /^Edit Trigger$/i })

    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    expect(nameInput.value).toBe('Marshals TV')
  })

  // Bug C — with two triggers, clicking Edit on each must surface that
  // trigger's data. Without a `key` on the editor, switching the editing
  // target reused stale useState values from the previous edit.
  it('Edit on trigger #1 shows trigger #1 even after editing trigger #2 first', async () => {
    vi.mocked(listTriggers).mockResolvedValue([WATCH_TRIGGER, SECOND_TRIGGER])
    render(<AutomationsPage />, { wrapper: wrapper() })
    await screen.findByText('Marshals TV')
    await screen.findByText('Movies Library')

    let editButtons = screen.getAllByRole('button', { name: /^edit$/i })
    fireEvent.click(editButtons[1])
    await screen.findByRole('heading', { name: /^Edit Trigger$/i })
    let nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    expect(nameInput.value).toBe('Movies Library')

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))

    editButtons = await screen.findAllByRole('button', { name: /^edit$/i })
    fireEvent.click(editButtons[0])
    await screen.findByRole('heading', { name: /^Edit Trigger$/i })
    nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement
    expect(nameInput.value).toBe('Marshals TV')
  })
})
