import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import VerificationBadge from './VerificationBadge'

describe('VerificationBadge', () => {
  it('renders nothing when status is null', () => {
    const { container } = render(<VerificationBadge status={null} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('shows pass', () => {
    render(<VerificationBadge status="pass" />)
    expect(screen.getByText(/verified/i)).toBeInTheDocument()
  })
  it('shows fail', () => {
    render(<VerificationBadge status="fail" />)
    expect(screen.getByText(/failed/i)).toBeInTheDocument()
  })
  it('shows verifying', () => {
    render(<VerificationBadge status="running" />)
    expect(screen.getByText(/verifying/i)).toBeInTheDocument()
  })
})
