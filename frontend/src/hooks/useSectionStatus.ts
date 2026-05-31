import { useCallback, useEffect } from 'react'
import { apiFetch } from '@/lib/api'
import { SECTIONS, type SectionId } from '@/pages/Settings/sections'
import { useSettingsStatusStore, type SectionStatus } from '@/store/settingsStatusStore'

export function useSectionStatus(id: SectionId): SectionStatus & { check: () => Promise<void> } {
  const current = useSettingsStatusStore((s) => s.byId[id]) ?? { status: 'idle', detail: null }
  const setStatus = useSettingsStatusStore((s) => s.set)
  const probe = SECTIONS.find((s) => s.id === id)?.probe ?? null

  const check = useCallback(async () => {
    if (!probe) return
    setStatus(id, { status: 'checking', detail: null })
    try {
      // Real backend contract is TestConnectivityResponse { ok, detail }
      // (app/models/schemas.py) — branch on `ok`, and only ever store a
      // string detail (never let an object reach the pill).
      const r = await apiFetch<{ ok?: boolean; detail?: unknown }>(probe.path, {
        method: probe.method,
        ...(probe.body ? { body: JSON.stringify(probe.body) } : {}),
      })
      const detail = typeof r.detail === 'string' ? r.detail : null
      setStatus(id, r.ok === false
        ? { status: 'warn', detail: detail ?? 'Reachable but misconfigured' }
        : { status: 'ok', detail })
    } catch (e) {
      setStatus(id, { status: 'error', detail: e instanceof Error ? e.message : 'Unreachable' })
    }
  }, [id, probe, setStatus])

  useEffect(() => {
    if (probe && current.status === 'idle') check().catch(() => {})
  }, [probe, current.status, check])

  return { ...current, check }
}
