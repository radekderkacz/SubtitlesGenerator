import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import PhaseTimeline from './PhaseTimeline'
import type { JobPhase, JobStatus } from '@/types/api'

function statesByStep(): Record<string, string> {
  const items = screen.getAllByRole('listitem')
  const out: Record<string, string> = {}
  for (const item of items) {
    const el = item as HTMLElement
    out[el.dataset.step ?? ''] = el.dataset.state ?? ''
  }
  return out
}

describe('PhaseTimeline', () => {
  const cases: ReadonlyArray<{
    name: string
    status: JobStatus
    phase: JobPhase | null
    expected: Record<string, string>
  }> = [
    {
      name: 'queued',
      status: 'queued',
      phase: null,
      expected: {
        queued: 'active', extracting: 'pending', transcribing: 'pending',
        translating: 'pending', writing: 'pending', done: 'pending',
      },
    },
    {
      name: 'processing → extracting',
      status: 'processing',
      phase: 'extracting',
      expected: {
        queued: 'completed', extracting: 'active', transcribing: 'pending',
        translating: 'pending', writing: 'pending', done: 'pending',
      },
    },
    {
      name: 'processing → transcribing',
      status: 'processing',
      phase: 'transcribing',
      expected: {
        queued: 'completed', extracting: 'completed', transcribing: 'active',
        translating: 'pending', writing: 'pending', done: 'pending',
      },
    },
    {
      name: 'processing → writing',
      status: 'processing',
      phase: 'writing',
      expected: {
        queued: 'completed', extracting: 'completed', transcribing: 'completed',
        translating: 'completed', writing: 'active', done: 'pending',
      },
    },
    {
      name: 'completed',
      status: 'completed',
      phase: 'done',
      expected: {
        queued: 'completed', extracting: 'completed', transcribing: 'completed',
        translating: 'completed', writing: 'completed', done: 'completed',
      },
    },
    {
      name: 'failed during transcribing',
      status: 'failed',
      phase: 'transcribing',
      expected: {
        queued: 'completed', extracting: 'completed', transcribing: 'failed',
        translating: 'pending', writing: 'pending', done: 'pending',
      },
    },
    {
      name: 'cancelled mid-pipeline',
      status: 'cancelled',
      phase: 'translating',
      expected: {
        queued: 'completed', extracting: 'completed', transcribing: 'completed',
        translating: 'cancelled', writing: 'pending', done: 'pending',
      },
    },
    {
      name: 'failed pre-pickup (phase null)',
      status: 'failed',
      phase: null,
      expected: {
        queued: 'failed', extracting: 'pending', transcribing: 'pending',
        translating: 'pending', writing: 'pending', done: 'pending',
      },
    },
  ]

  it.each(cases)('$name → correct step states', ({ status, phase, expected }) => {
    render(<PhaseTimeline status={status} phase={phase} />)
    expect(statesByStep()).toEqual(expected)
  })

  it('marks the active step with the animate-pulse class', () => {
    const { container } = render(<PhaseTimeline status="processing" phase="transcribing" />)
    const active = container.querySelector('[data-state="active"]')
    expect(active?.querySelector('.animate-pulse')).toBeInTheDocument()
  })
})
