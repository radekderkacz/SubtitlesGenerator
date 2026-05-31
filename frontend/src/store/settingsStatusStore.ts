import { create } from 'zustand'
import type { SectionId } from '@/pages/Settings/sections'

export type ProbeStatus = 'idle' | 'checking' | 'ok' | 'warn' | 'error'
export type SectionStatus = Readonly<{ status: ProbeStatus; detail: string | null }>

type State = {
  byId: Partial<Record<SectionId, SectionStatus>>
  get: (id: SectionId) => SectionStatus
  set: (id: SectionId, s: SectionStatus) => void
}

const IDLE: SectionStatus = { status: 'idle', detail: null }

export const useSettingsStatusStore = create<State>((set, get) => ({
  byId: {},
  get: (id) => get().byId[id] ?? IDLE,
  set: (id, s) => set((st) => ({ byId: { ...st.byId, [id]: s } })),
}))
