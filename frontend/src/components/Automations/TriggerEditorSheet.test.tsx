import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TriggerEditorSheet from './TriggerEditorSheet'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn().mockResolvedValue({ profiles: [{ name: 'Profile1' }] }),
  createTrigger: vi.fn().mockResolvedValue({ id: 'new-id' }),
  updateTrigger: vi.fn().mockResolvedValue({ id: 'existing-id' }),
  fireTrigger: vi.fn().mockResolvedValue({ fired: 3 }),
  previewCron: vi.fn().mockResolvedValue({ next_fires: [] }),
  browseDirectory: vi.fn().mockResolvedValue({
    path: '/shared/TV',
    parent: '/shared',
    directories: [],
    files: [],
  }),
}))

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

beforeEach(async () => {
  const api = await import('@/lib/api')
  vi.mocked(api.createTrigger).mockClear()
  vi.mocked(api.fireTrigger).mockClear()
  // Default new-id (overridden per test where the returned id matters)
  vi.mocked(api.createTrigger).mockResolvedValue({ id: 'new-id' } as never)
})

describe('TriggerEditorSheet', () => {
  it('submits create payload for a watch trigger with action + file_filter', async () => {
    const qc = makeQC()
    const onOpenChange = vi.fn()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TriggerEditorSheet open={true} onOpenChange={onOpenChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(await screen.findByLabelText(/name/i), {
      target: { value: 'TV Shows' },
    })
    // type=watch is default; save
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    const { createTrigger } = await import('@/lib/api')
    await vi.waitFor(() => expect(vi.mocked(createTrigger)).toHaveBeenCalledOnce())
    const payload = vi.mocked(createTrigger).mock.calls[0][0]
    expect(payload).toMatchObject({
      name: 'TV Shows',
      type: 'watch',
      action: expect.objectContaining({ profile_name: expect.any(String) }),
      file_filter: expect.objectContaining({ type: 'all' }),
    })
    // No 'rules' key
    expect(payload).not.toHaveProperty('rules')
  })

  // Bug B — Watch triggers fire on new file events only. A folder that
  // already contains movies without SRTs is dead until somebody touches a
  // file. The editor must offer to scan existing files when the trigger
  // is first saved.
  it('fires the trigger after save when "Scan existing files" is checked (watch type, new trigger)', async () => {
    const qc = makeQC()
    const onOpenChange = vi.fn()
    const api = await import('@/lib/api')
    vi.mocked(api.createTrigger).mockResolvedValue({ id: 'fresh-id' } as never)

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TriggerEditorSheet open={true} onOpenChange={onOpenChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(await screen.findByLabelText(/^name$/i), {
      target: { value: 'New Show' },
    })
    fireEvent.click(
      screen.getByRole('checkbox', { name: /scan existing files/i }),
    )
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await vi.waitFor(() =>
      expect(vi.mocked(api.createTrigger)).toHaveBeenCalledOnce(),
    )
    await vi.waitFor(() =>
      expect(vi.mocked(api.fireTrigger)).toHaveBeenCalledWith('fresh-id'),
    )
  })

  it('does NOT fire the trigger when "Scan existing files" is unchecked', async () => {
    const qc = makeQC()
    const onOpenChange = vi.fn()
    const api = await import('@/lib/api')

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TriggerEditorSheet open={true} onOpenChange={onOpenChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(await screen.findByLabelText(/^name$/i), {
      target: { value: 'Quiet Watch' },
    })
    // Leave checkbox unchecked
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await vi.waitFor(() =>
      expect(vi.mocked(api.createTrigger)).toHaveBeenCalledOnce(),
    )
    expect(vi.mocked(api.fireTrigger)).not.toHaveBeenCalled()
  })

  it('includes schedule in config for cron trigger', async () => {
    const qc = makeQC()
    const onOpenChange = vi.fn()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TriggerEditorSheet open={true} onOpenChange={onOpenChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    // Switch to cron
    fireEvent.change(await screen.findByLabelText(/name/i), {
      target: { value: 'Night scan' },
    })
    fireEvent.click(screen.getByRole('button', { name: /cron/i }))
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    const { createTrigger } = await import('@/lib/api')
    await vi.waitFor(() => expect(vi.mocked(createTrigger)).toHaveBeenCalledOnce())
    const payload = vi.mocked(createTrigger).mock.calls[0][0]
    expect(payload).toMatchObject({
      name: 'Night scan',
      type: 'cron',
      action: expect.objectContaining({ profile_name: expect.any(String) }),
      file_filter: expect.objectContaining({ type: 'all' }),
    })
    expect(payload.config).toHaveProperty('schedule')
    expect(payload).not.toHaveProperty('rules')
  })
})
