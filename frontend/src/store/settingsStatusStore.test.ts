import { describe, it, expect, beforeEach } from 'vitest'
import { useSettingsStatusStore } from './settingsStatusStore'

const reset = () => useSettingsStatusStore.setState({ byId: {} })

describe('settingsStatusStore', () => {
  beforeEach(reset)
  it('defaults a section to idle', () => {
    expect(useSettingsStatusStore.getState().get('jellyfin')).toEqual({ status: 'idle', detail: null })
  })
  it('sets and reads a section result', () => {
    useSettingsStatusStore.getState().set('jellyfin', { status: 'ok', detail: null })
    expect(useSettingsStatusStore.getState().get('jellyfin').status).toBe('ok')
  })
})
