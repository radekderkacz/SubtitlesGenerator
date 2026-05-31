import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SectionHeader from './SectionHeader'

describe('SectionHeader', () => {
  it('renders title, description and a status pill', () => {
    render(<SectionHeader title="Jellyfin" description="Media server." status="ok" />)
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument()
    expect(screen.getByText('Media server.')).toBeInTheDocument()
    expect(screen.getByTestId('section-status')).toHaveAttribute('data-status', 'ok')
  })
  it('renders an action slot', () => {
    render(<SectionHeader title="X" description="y" status="idle" action={<button>Test</button>} />)
    expect(screen.getByRole('button', { name: 'Test' })).toBeInTheDocument()
  })
})
