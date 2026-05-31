import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

// Mock the section catalog so the hook is exercised against a controlled
// probed / unprobed pair — independent of which real sections happen to
// have a probe (none currently do; jellyfin/ai-backends are driven by
// their explicit Test handlers). Responses use the REAL backend contract
// TestConnectivityResponse { ok, detail } (app/models/schemas.py) — not
// an invented `{success}` shape that would pass against the old bug.
vi.mock('@/pages/Settings/sections', () => ({
  SECTIONS: [
    {
      id: 'probed',
      label: 'Probed',
      group: 'AI',
      description: '',
      probe: { path: '/api/v1/test', method: 'POST' },
    },
    { id: 'unprobed', label: 'Unprobed', group: 'AI', description: '', probe: null },
  ],
}))
vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

import { useSectionStatus } from './useSectionStatus'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'
import { apiFetch } from '@/lib/api'

const probed = (): never => 'probed' as never
const unprobed = (): never => 'unprobed' as never

beforeEach(() => {
  useSettingsStatusStore.setState({ byId: {} })
  vi.mocked(apiFetch).mockReset()
})

describe('useSectionStatus', () => {
  it('stays idle for a section with no probe', () => {
    const { result } = renderHook(() => useSectionStatus(unprobed()))
    expect(result.current.status).toBe('idle')
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it('probes once on first mount and caches', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true } as never)
    const { result, unmount } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('ok'))
    unmount()
    renderHook(() => useSectionStatus(probed()))
    expect(apiFetch).toHaveBeenCalledTimes(1) // cache hit, no re-probe
  })

  it('error status on probe failure, never throws', async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('error'))
  })

  it('maps backend ok:false to warn with its detail', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: false, detail: 'Auth failed' } as never)
    const { result } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('warn'))
    expect(result.current.detail).toBe('Auth failed')
  })

  it('surfaces the backend success detail on ok', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, detail: 'Connected — Jellyfin 10.8' } as never)
    const { result } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('ok'))
    expect(result.current.detail).toBe('Connected — Jellyfin 10.8')
  })

  it('never lets a non-string detail reach the pill', async () => {
    // Defensive: even if a probe response carried a structured detail,
    // the hook must store a string|null — never an object.
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, detail: { nested: 'x' } } as never)
    const { result } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('ok'))
    expect(result.current.detail).toBeNull()
  })

  it('check() forces a re-probe', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true } as never)
    const { result } = renderHook(() => useSectionStatus(probed()))
    await waitFor(() => expect(result.current.status).toBe('ok'))
    await act(() => result.current.check())
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })
})
