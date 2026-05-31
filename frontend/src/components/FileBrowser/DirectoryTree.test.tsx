import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DirectoryTree from './DirectoryTree'

vi.mock('@/lib/api', () => ({
  browseDirectory: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.name = 'ApiRequestError'
      this.status = status
      this.code = code
    }
  },
}))

function renderTree(props: Partial<Parameters<typeof DirectoryTree>[0]> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <DirectoryTree
          selectedPath={props.selectedPath ?? null}
          onSelect={props.onSelect ?? (() => {})}
        />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('DirectoryTree', () => {
  beforeEach(async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders a loading indicator while the root request is in flight', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockReturnValue(new Promise(() => {}))
    renderTree()
    expect(screen.getByText(/Loading directory tree/)).toBeInTheDocument()
  })

  it('renders the not-configured empty state with Open Settings link', async () => {
    const { browseDirectory, ApiRequestError } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockRejectedValue(
      new ApiRequestError(422, 'NAS_NOT_CONFIGURED', 'NAS mount path is not configured'),
    )
    renderTree()
    expect(
      await screen.findByText(/No media root configured/),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Open Settings' })
    expect(link).toHaveAttribute('href', '/settings')
  })

  it('renders a generic error state for other API errors', async () => {
    const { browseDirectory, ApiRequestError } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Backend exploded'),
    )
    renderTree()
    expect(await screen.findByText(/Failed to load directory tree/)).toBeInTheDocument()
    expect(screen.getByText('Backend exploded')).toBeInTheDocument()
  })

  it('renders the root path and its top-level subdirectories', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media',
      parent: null,
      directories: ['films', 'tv-shows', 'anime'],
      files: [],
    })
    renderTree()
    expect(await screen.findByText('/media')).toBeInTheDocument()
    expect(screen.getByText('films')).toBeInTheDocument()
    expect(screen.getByText('tv-shows')).toBeInTheDocument()
    expect(screen.getByText('anime')).toBeInTheDocument()
  })

  it('shows "No subdirectories" when the root has no children', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media',
      parent: null,
      directories: [],
      files: [],
    })
    renderTree()
    expect(await screen.findByText('No subdirectories')).toBeInTheDocument()
  })

  it('lazy-loads children when a folder is expanded', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory)
      .mockResolvedValueOnce({
        path: '/media',
        parent: null,
        directories: ['films'],
        files: [],
      })
      .mockResolvedValueOnce({
        path: '/media/films',
        parent: '/media',
        directories: ['foreign', 'classic'],
        files: [],
      })

    renderTree()
    await screen.findByText('films')
    // Children NOT yet loaded — no second API call
    expect(vi.mocked(browseDirectory)).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Expand films' }))

    expect(await screen.findByText('foreign')).toBeInTheDocument()
    expect(screen.getByText('classic')).toBeInTheDocument()
    expect(vi.mocked(browseDirectory)).toHaveBeenCalledWith('/media/films')
  })

  it('calls onSelect with the folder path when its label is clicked', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media',
      parent: null,
      directories: ['films'],
      files: [],
    })
    const onSelect = vi.fn()
    renderTree({ onSelect })

    const button = await screen.findByRole('button', { name: /^films$/ })
    fireEvent.click(button)
    expect(onSelect).toHaveBeenCalledWith('/media/films')
  })

  it('highlights the selected folder via aria-current on the list item', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media',
      parent: null,
      directories: ['films'],
      files: [],
    })
    const { container } = renderTree({ selectedPath: '/media/films' })

    await screen.findByText('films')
    const selectedItem = container.querySelector('li[aria-current="true"]')
    expect(selectedItem).toBeInTheDocument()
    expect(selectedItem).toHaveTextContent('films')
  })

  it('toggles expansion via Enter key on the folder label', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory)
      .mockResolvedValueOnce({
        path: '/media',
        parent: null,
        directories: ['films'],
        files: [],
      })
      .mockResolvedValueOnce({
        path: '/media/films',
        parent: '/media',
        directories: ['foreign'],
        files: [],
      })

    renderTree()
    const filmsButton = await screen.findByRole('button', { name: /^films$/ })
    fireEvent.keyDown(filmsButton, { key: 'Enter' })
    expect(await screen.findByText('foreign')).toBeInTheDocument()
  })
})
