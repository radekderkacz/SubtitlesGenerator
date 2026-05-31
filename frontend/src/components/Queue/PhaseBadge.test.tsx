import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import PhaseBadge from './PhaseBadge'

describe('PhaseBadge', () => {
  const cases: ReadonlyArray<{
    status: Parameters<typeof PhaseBadge>[0]['status']
    phase: Parameters<typeof PhaseBadge>[0]['phase']
    label: string
    cssVar: string
  }> = [
    { status: 'queued', phase: null, label: 'Queued', cssVar: '--phase-queued' },
    { status: 'processing', phase: 'extracting', label: 'Extracting', cssVar: '--phase-extracting' },
    { status: 'processing', phase: 'transcribing', label: 'Transcribing', cssVar: '--phase-transcribing' },
    { status: 'processing', phase: 'translating', label: 'Translating', cssVar: '--phase-translating' },
    { status: 'processing', phase: 'writing', label: 'Writing', cssVar: '--phase-writing' },
    { status: 'processing', phase: null, label: 'Processing', cssVar: '--phase-transcribing' },
    { status: 'completed', phase: null, label: 'Done', cssVar: '--phase-done' },
    { status: 'failed', phase: null, label: 'Failed', cssVar: '--phase-failed' },
    { status: 'cancelled', phase: null, label: 'Cancelled', cssVar: '--phase-cancelled' },
  ]

  it.each(cases)(
    'renders $label for status=$status phase=$phase using $cssVar',
    ({ status, phase, label, cssVar }) => {
      const { unmount } = render(<PhaseBadge status={status} phase={phase} />)
      const badge = screen.getByLabelText(`Phase: ${label}`)
      expect(badge).toHaveTextContent(label)
      expect(badge.style.backgroundColor).toBe(`var(${cssVar})`)
      unmount()
    },
  )

  it('applies the 150ms transition classes for phase fade', () => {
    render(<PhaseBadge status="processing" phase="transcribing" />)
    const badge = screen.getByLabelText('Phase: Transcribing')
    expect(badge.className).toContain('transition-colors')
    expect(badge.className).toContain('duration-150')
  })
})
