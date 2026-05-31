import { create } from 'zustand'
import type { Job, JobUpdatePayload } from '@/types/api'

type JobStore = {
  jobs: Job[]
  isConnected: boolean
  // Timestamp (ms) of the last SSE event of any kind (queue_state, job_update,
  // heartbeat). The connection indicator derives staleness from this.
  lastEventAt: number | null
  setJobs: (jobs: Job[]) => void
  applyJobUpdate: (update: JobUpdatePayload) => void
  setConnected: (value: boolean) => void
  markEventReceived: () => void
}

export const useJobStore = create<JobStore>((set) => ({
  jobs: [],
  isConnected: false,
  lastEventAt: null,
  setJobs: (jobs) => set({ jobs }),
  applyJobUpdate: (update) =>
    set((state) => {
      const idx = state.jobs.findIndex((j) => j.id === update.id)
      if (idx === -1) {
        // Unknown ID — store the partial as-is until a queue_state fills it.
        // Casting because incoming payload has only AC-#3 fields; the Job type's
        // remaining fields stay undefined until the next queue_state replay.
        return { jobs: [...state.jobs, update as unknown as Job] }
      }
      const jobs = [...state.jobs]
      // The cast is needed because JobUpdatePayload carries optional
      // failure-only fields (file_path?, error_message?) that TS sees as
      // possibly-undefined and therefore not assignable to Job's stricter
      // shape. At runtime the spread overwrites with the new values only
      // when they're actually present, which is the correct behavior.
      jobs[idx] = { ...jobs[idx], ...update } as Job
      return { jobs }
    }),
  setConnected: (value) =>
    set((state) => (state.isConnected === value ? state : { isConnected: value })),
  markEventReceived: () => set({ lastEventAt: Date.now() }),
}))
