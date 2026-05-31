import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FileList from './FileList'

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

function renderList(props: Partial<Parameters<typeof FileList>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FileList path={props.path ?? '/media/films'} onFileClick={props.onFileClick ?? (() => {})} />
    </QueryClientProvider>,
  )
}

describe('FileList', () => {
  beforeEach(async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders skeleton rows while the API is in flight', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockReturnValue(new Promise(() => {}))
    renderList()
    expect(screen.getByLabelText('Loading files')).toBeInTheDocument()
  })

  it('renders the empty state when the directory has no video files', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media/films',
      parent: '/media',
      directories: [],
      files: [],
    })
    renderList()
    expect(
      await screen.findByText('No video files in this directory.'),
    ).toBeInTheDocument()
  })

  it('renders an error alert when the request fails', async () => {
    const { browseDirectory, ApiRequestError } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockRejectedValue(
      new ApiRequestError(500, 'INTERNAL_ERROR', 'Server exploded'),
    )
    renderList()
    expect(await screen.findByRole('alert')).toHaveTextContent('Server exploded')
  })

  it('renders a row per file with name, size, modified and SRT badge', async () => {
    const { browseDirectory } = await import('@/lib/api')
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media/films',
      parent: '/media',
      directories: [],
      files: [
        {
          name: 'Film.mkv',
          size_bytes: 8_500_000_000,
          modified_at: '2026-04-24T10:00:00Z',
          has_srt: true,
        },
        {
          name: 'Other.mkv',
          size_bytes: 4_200_000_000,
          modified_at: '2026-04-22T08:00:00Z',
          has_srt: false,
        },
      ],
    })
    renderList()

    expect(await screen.findByText('Film.mkv')).toBeInTheDocument()
    expect(screen.getByText('Other.mkv')).toBeInTheDocument()

    // formatBytes(8_500_000_000) → "7.9 GB"; formatBytes(4_200_000_000) → "3.9 GB"
    expect(screen.getByText('7.9 GB')).toBeInTheDocument()
    expect(screen.getByText('3.9 GB')).toBeInTheDocument()

    // SrtBadge: one "Has SRT" + one "No SRT"
    expect(screen.getAllByLabelText('Has SRT')).toHaveLength(1)
    expect(screen.getAllByLabelText('No SRT')).toHaveLength(1)
  })

  it('calls onFileClick with the file and full path when a row is clicked', async () => {
    const { browseDirectory } = await import('@/lib/api')
    const file = {
      name: 'Film.mkv',
      size_bytes: 100,
      modified_at: '2026-04-24T10:00:00Z',
      has_srt: false,
    }
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media/films',
      parent: '/media',
      directories: [],
      files: [file],
    })
    const onClick = vi.fn()
    renderList({ onFileClick: onClick })

    fireEvent.click(await screen.findByText('Film.mkv'))
    expect(onClick).toHaveBeenCalledWith(file, '/media/films/Film.mkv')
  })

  it('triggers onFileClick on Enter / Space keys', async () => {
    const { browseDirectory } = await import('@/lib/api')
    const file = {
      name: 'Film.mkv',
      size_bytes: 100,
      modified_at: '2026-04-24T10:00:00Z',
      has_srt: false,
    }
    vi.mocked(browseDirectory).mockResolvedValueOnce({
      path: '/media/films',
      parent: '/media',
      directories: [],
      files: [file],
    })
    const onClick = vi.fn()
    const { container } = renderList({ onFileClick: onClick })

    await screen.findByText('Film.mkv')
    const row = container.querySelector('tr[tabindex="0"]') as HTMLElement
    fireEvent.keyDown(row, { key: 'Enter' })
    fireEvent.keyDown(row, { key: ' ' })
    expect(onClick).toHaveBeenCalledTimes(2)
  })
})
