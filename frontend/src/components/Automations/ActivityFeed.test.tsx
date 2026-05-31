import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ActivityFeed from './ActivityFeed'

vi.mock('@/lib/api', () => ({
  listTriggerEvents: vi.fn().mockResolvedValue([
    {
      id: 'e1',
      trigger_id: 't1',
      fired_at: '2026-05-20T14:32:00Z',
      event_payload: { file_path: '/shared/TV/X.mkv' },
      matched_rule_index: 0,
      outcome: 'submitted',
      job_id: 'j1',
      error_message: null,
    },
  ]),
}))

describe('ActivityFeed', () => {
  it('renders one row per event and shows outcome chip', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <ActivityFeed />
      </QueryClientProvider>,
    )
    expect(await screen.findByText(/X\.mkv/)).toBeInTheDocument()
    expect(screen.getByText(/submitted/i)).toBeInTheDocument()
  })

  it('Failed tab filters by outcome', async () => {
    const { listTriggerEvents } = await import('@/lib/api')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <ActivityFeed />
      </QueryClientProvider>,
    )
    await screen.findByText(/X\.mkv/)
    fireEvent.click(screen.getByRole('tab', { name: /failed/i }))
    expect(vi.mocked(listTriggerEvents)).toHaveBeenLastCalledWith({
      outcome: 'failed_dispatch',
      limit: 100,
    })
  })
})
