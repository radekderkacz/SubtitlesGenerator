import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { browseDirectory } from '@/lib/api'
import FileBrowserPage from './FileBrowserPage'

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
  apiFetch: vi.fn(),
  submitJob: vi.fn(),
}))

// BatchPanel and BatchSelectionStrip depend on router + react-query which are
// already provided by renderPage(); no extra mocking needed.
const MOCK_FILE = {
  name: 'movie.mkv',
  size_bytes: 1024,
  modified_at: '2024-01-01T00:00:00Z',
  has_srt: false,
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [{ path: '/', element: <FileBrowserPage /> }, { path: '/settings', element: <div>settings</div> }],
    { initialEntries: ['/'] },
  )
  return { qc, ...render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )}
}

beforeEach(() => {
  vi.mocked(browseDirectory).mockReset()
})

describe('FileBrowserPage', () => {
  it('bounds the page to the viewport so columns scroll independently', () => {
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media',
      parent: null,
      directories: [],
      files: [],
    })
    const { container } = renderPage()
    const root = container.querySelector('div')!
    expect(root.className).not.toMatch(/min-h-screen/)
    expect(root.className).toMatch(/h-\[100dvh\]|h-screen|h-full/)
  })

  it('renders the FILE SYSTEM caption header and the empty selection state', async () => {
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media',
      parent: null,
      directories: [],
      files: [],
    })
    renderPage()
    expect(await screen.findByText('Locations')).toBeInTheDocument()
    expect(
      screen.getByText('Select a folder from Locations to see its files.'),
    ).toBeInTheDocument()
  })

  it('renders the refresh button with the right aria-label', async () => {
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media',
      parent: null,
      directories: [],
      files: [],
    })
    renderPage()
    expect(
      await screen.findByRole('button', { name: 'Refresh file system' }),
    ).toBeInTheDocument()
  })

  it('clicking refresh invalidates the browse query', async () => {
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media',
      parent: null,
      directories: [],
      files: [],
    })
    const { qc } = renderPage()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh file system' }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['browse'] }))
  })

  it('renders the directory tree heading exposed by DirectoryTree', async () => {
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media',
      parent: null,
      directories: ['films', 'tv'],
      files: [],
    })
    renderPage()
    // DirectoryTree shows the root path once it loads
    expect(await screen.findByText('/media')).toBeInTheDocument()
    // Subdirectory entries
    expect(screen.getByText('films')).toBeInTheDocument()
    expect(screen.getByText('tv')).toBeInTheDocument()
  })

  it('selecting a file shows the BatchSelectionStrip and BatchPanel in the right rail', async () => {
    // Root browse: one directory entry so it appears in DirectoryTree
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media',
      parent: null,
      directories: ['films'],
      files: [],
    })
    // Directory browse (triggered when user clicks 'films'): one video file
    vi.mocked(browseDirectory).mockResolvedValue({
      path: '/media/films',
      parent: '/media',
      directories: [],
      files: [MOCK_FILE],
    })
    renderPage()

    // Click 'films' in the directory tree to set selectedPath = '/media/films'
    const folderBtn = await screen.findByRole('button', { name: 'films' })
    fireEvent.click(folderBtn)

    // Wait for the file row checkbox to appear
    const checkbox = await screen.findByRole('checkbox', {
      name: /Select movie\.mkv for batch submission/i,
    })
    fireEvent.click(checkbox)

    // (a) Slim strip: shows "N selected" and a Clear button
    // (BatchSelectionStrip and BatchActionBar both render this text; assert at least one)
    await waitFor(() => {
      const matches = screen.getAllByText(/1 files? selected/i)
      expect(matches.length).toBeGreaterThan(0)
    })
    const clearBtns = screen.getAllByRole('button', { name: /clear/i })
    expect(clearBtns.length).toBeGreaterThan(0)

    // (b) BatchPanel heading in the right rail
    expect(screen.getByText(/Generate for 1 file/i)).toBeInTheDocument()
  })
})
