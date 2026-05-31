import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import SettingsRail from './SettingsRail'

const r = (active = 'media') =>
  render(<MemoryRouter><SettingsRail active={active as never} /></MemoryRouter>)

describe('SettingsRail', () => {
  it('renders the three group eyebrows', () => {
    r()
    for (const g of ['STORAGE', 'INTEGRATIONS', 'AI']) expect(screen.getByText(g)).toBeInTheDocument()
  })
  it('renders all four sections as links', () => {
    r()
    for (const n of ['Media Library','Jellyfin','AI Backends','Saved Configurations'])
      expect(screen.getByRole('link', { name: new RegExp(n, 'i') })).toBeInTheDocument()
  })
  it('marks the active section', () => {
    r('jellyfin')
    expect(screen.getByRole('link', { name: /Jellyfin/i })).toHaveAttribute('aria-current', 'page')
  })
  it('each item shows a status dot', () => {
    r()
    expect(screen.getAllByTestId('section-status')).toHaveLength(4)
  })
})
