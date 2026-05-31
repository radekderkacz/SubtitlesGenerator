import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import TriggerCard from './TriggerCard'
import type { Trigger } from '@/types/api'

const t: Trigger = {
  id: 't1',
  name: 'Marshals TV',
  type: 'watch',
  config: { path: '/shared/TV/Marshals' },
  action: {
    profile_name: 'P1',
    source_language: null,
    target_language: null,
    skip_if_srt: true,
  },
  file_filter: { type: 'all', value: null },
  enabled: true,
  created_at: '2026-05-20T00:00:00Z',
  updated_at: '2026-05-20T00:00:00Z',
  last_fired_at: '2026-05-20T14:32:00Z',
  fire_count_24h: 5,
}

describe('TriggerCard', () => {
  it('renders name, type label, and fire stats', () => {
    render(
      <MemoryRouter>
        <TriggerCard trigger={t} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Marshals TV')).toBeInTheDocument()
    expect(screen.getByText(/watch folder/i)).toBeInTheDocument()
    expect(screen.getByText(/5×/)).toBeInTheDocument()
  })

  it('shows paused pill when disabled', () => {
    render(
      <MemoryRouter>
        <TriggerCard trigger={{ ...t, enabled: false }} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/paused/i)).toBeInTheDocument()
  })

  it('hides Run now for webhook triggers (encodes the §7 rule)', () => {
    const w: Trigger = { ...t, type: 'webhook', config: {} }
    render(
      <MemoryRouter>
        <TriggerCard trigger={w} />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('button', { name: /run now/i })).toBeNull()
    expect(screen.getByRole('button', { name: /reveal secret/i })).toBeInTheDocument()
  })
})
