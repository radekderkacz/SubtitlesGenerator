import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import SrtBadge from './SrtBadge'

describe('SrtBadge', () => {
  it('renders the green "SRT" badge with check icon when hasSrt=true', () => {
    render(<SrtBadge hasSrt={true} />)
    const badge = screen.getByLabelText('Has SRT')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('SRT')
    expect(badge.className).toContain('emerald')
  })

  it('renders the muted "No SRT" badge when hasSrt=false', () => {
    render(<SrtBadge hasSrt={false} />)
    const badge = screen.getByLabelText('No SRT')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('No SRT')
    expect(badge.className).toContain('muted-foreground')
  })
})
