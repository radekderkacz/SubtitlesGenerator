import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import VerificationBadge from './VerificationBadge'

describe('VerificationBadge', () => {
  it('renders nothing when status is null', () => {
    const { container } = render(<VerificationBadge status={null} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('shows friendly pass label and no numeric score', () => {
    render(<VerificationBadge status="pass" score={95} />)
    expect(screen.getByText('Looks good')).toBeInTheDocument()
    expect(screen.queryByText(/95/)).not.toBeInTheDocument()
  })
  it('shows friendly warn label', () => {
    render(<VerificationBadge status="warn" />)
    expect(screen.getByText('Worth a look')).toBeInTheDocument()
  })
  it('shows friendly fail label', () => {
    render(<VerificationBadge status="fail" />)
    expect(screen.getByText('Needs attention')).toBeInTheDocument()
  })
  it('shows checking label for running', () => {
    render(<VerificationBadge status="running" />)
    expect(screen.getByText('Checking…')).toBeInTheDocument()
  })
})
