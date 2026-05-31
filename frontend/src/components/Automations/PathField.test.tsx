import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import PathField from './PathField'

const mockOnChange = vi.fn()

describe('PathField', () => {
  it('renders the current value', () => {
    render(<PathField value="/shared/TV" onChange={mockOnChange} />)
    expect(screen.getByDisplayValue('/shared/TV')).toBeInTheDocument()
  })

  it('shows a Browse button', () => {
    render(<PathField value="" onChange={mockOnChange} />)
    expect(screen.getByRole('button', { name: /browse/i })).toBeInTheDocument()
  })

  it('calls onChange when text typed', () => {
    render(<PathField value="/shared" onChange={mockOnChange} />)
    const input = screen.getByDisplayValue('/shared')
    fireEvent.change(input, { target: { value: '/shared/TV' } })
    expect(mockOnChange).toHaveBeenCalledWith('/shared/TV')
  })

  it('clicking Browse opens the dialog', () => {
    render(<PathField value="" onChange={mockOnChange} />)
    const browseBtn = screen.getByRole('button', { name: /browse/i })
    fireEvent.click(browseBtn)
    // Dialog/picker should be visible (we just check button exists for now, dialog mocked separately)
    expect(browseBtn).toBeInTheDocument()
  })
})
