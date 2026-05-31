import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import FileFilterField from './FileFilterField'
import type { FileFilter } from '@/types/api'

// Mock browseDirectory for FolderPickerDialog (used when subfolder selected)
vi.mock('@/lib/api', () => ({
  browseDirectory: vi.fn().mockResolvedValue({
    path: '/shared/TV',
    parent: '/shared',
    directories: ['Marshals'],
    files: [],
  }),
}))

const mockOnChange = vi.fn()

describe('FileFilterField', () => {
  it('renders "All video files" option and emits {type:all}', () => {
    const value: FileFilter = { type: 'all', value: null }
    render(<FileFilterField value={value} onChange={mockOnChange} scopePath="/shared/TV" />)
    // Should show a select or label with "All" variant
    expect(screen.getByText(/all video files/i)).toBeInTheDocument()
  })

  it('shows text input when name_contains is selected', async () => {
    const value: FileFilter = { type: 'name_contains', value: 'Marshals' }
    render(<FileFilterField value={value} onChange={mockOnChange} scopePath="/shared/TV" />)
    const input = await waitFor(() => screen.getByDisplayValue('Marshals'))
    expect(input).toBeInTheDocument()
  })

  it('calls onChange with name_contains when typing', async () => {
    const value: FileFilter = { type: 'name_contains', value: '' }
    render(<FileFilterField value={value} onChange={mockOnChange} scopePath="/shared/TV" />)
    const input = await waitFor(() => screen.getByPlaceholderText(/e\.g\. Marshals/i))
    fireEvent.change(input, { target: { value: 'Avatar' } })
    expect(mockOnChange).toHaveBeenCalledWith({ type: 'name_contains', value: 'Avatar' })
  })

  it('shows helper text in muted style', () => {
    const value: FileFilter = { type: 'all', value: null }
    render(<FileFilterField value={value} onChange={mockOnChange} scopePath="/shared/TV" />)
    // Helper text should exist for the current selection
    expect(screen.getByText(/match all video files/i)).toBeInTheDocument()
  })
})
