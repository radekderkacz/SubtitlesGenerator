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
})
