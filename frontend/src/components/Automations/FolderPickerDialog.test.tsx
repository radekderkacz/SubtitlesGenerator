import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import FolderPickerDialog from './FolderPickerDialog'

// Mock browseDirectory to return a fake directory structure
vi.mock('@/lib/api', () => ({
  browseDirectory: vi.fn().mockResolvedValue({
    path: '/shared',
    parent: null,
    directories: ['TV', 'Movies'],
    files: [],
  }),
}))

const mockOnSelect = vi.fn()
const mockOnOpenChange = vi.fn()

describe('FolderPickerDialog', () => {
  it('renders current path when open', async () => {
    render(
      <FolderPickerDialog
        open={true}
        onOpenChange={mockOnOpenChange}
        currentPath="/shared"
        onSelect={mockOnSelect}
      />
    )
    await waitFor(() => {
      expect(screen.getByText('/shared')).toBeInTheDocument()
    })
  })

  it('shows subdirectory entries', async () => {
    render(
      <FolderPickerDialog
        open={true}
        onOpenChange={mockOnOpenChange}
        currentPath="/shared"
        onSelect={mockOnSelect}
      />
    )
    await waitFor(() => {
      expect(screen.getByText('TV')).toBeInTheDocument()
      expect(screen.getByText('Movies')).toBeInTheDocument()
    })
  })

  it('calls onSelect with correct path on "Select this folder"', async () => {
    render(
      <FolderPickerDialog
        open={true}
        onOpenChange={mockOnOpenChange}
        currentPath="/shared"
        onSelect={mockOnSelect}
      />
    )
    await waitFor(() => {
      expect(screen.getByText('Select this folder')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Select this folder'))
    expect(mockOnSelect).toHaveBeenCalledWith('/shared')
  })

  it('falls back to the NAS root when the starting path is rejected', async () => {
    // Regression: a bad/relative/outside-the-mount currentPath used to
    // dead-end the dialog with "Path is outside NAS mount root". Browse
    // must instead fall back to the root and stay usable.
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockReset()
    vi.mocked(browseDirectory).mockImplementation(async (path?: string) => {
      if (path !== undefined) {
        throw new Error('Path is outside NAS mount root')
      }
      return { path: '/shared', parent: null, directories: ['TV', 'Movies'], files: [] }
    })
    render(
      <FolderPickerDialog
        open={true}
        onOpenChange={mockOnOpenChange}
        currentPath="Marshals"
        onSelect={mockOnSelect}
      />
    )
    // Recovered: shows the root + its dirs, NOT the error.
    await waitFor(() => {
      expect(screen.getByText('TV')).toBeInTheDocument()
    })
    expect(screen.queryByText(/outside NAS mount root/i)).not.toBeInTheDocument()
  })
})
