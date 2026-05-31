import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listTriggerEvents } from '@/lib/api'
import type { TriggerEventOutcome } from '@/types/api'

type Tab = 'all' | 'submitted' | 'skipped' | 'failed'

const TAB_LABELS: Record<Tab, string> = {
  all: 'All',
  submitted: 'Jobs',
  skipped: 'Skipped',
  failed: 'Failed',
}

const TAB_OUTCOMES: Record<Tab, TriggerEventOutcome | undefined> = {
  all: undefined,
  submitted: 'submitted',
  skipped: 'skipped_no_rule',
  failed: 'failed_dispatch',
}

const OUTCOME_CHIP: Record<string, string> = {
  submitted: 'bg-emerald-500/20 text-emerald-400',
  skipped_no_rule: 'bg-zinc-500/20 text-zinc-400',
  skipped_existing_srt: 'bg-zinc-500/20 text-zinc-400',
  skipped_duplicate: 'bg-zinc-500/20 text-zinc-400',
  skipped_scan_limit: 'bg-amber-500/20 text-amber-400',
  failed_dispatch: 'bg-red-500/20 text-red-400',
}

export default function ActivityFeed() {
  const [tab, setTab] = useState<Tab>('all')
  const [expanded, setExpanded] = useState<string | null>(null)

  const outcome = TAB_OUTCOMES[tab]
  const { data: events = [], isLoading } = useQuery({
    queryKey: ['trigger_events', outcome],
    queryFn: () => listTriggerEvents({ outcome, limit: 100 }),
    refetchInterval: 10_000,
  })

  return (
    <div className="bg-card rounded-xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] border border-white/[0.05]">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-white/5">
        <h2 className="text-xl font-semibold text-foreground mb-1">Recent Activity</h2>
        <p className="text-sm text-muted-foreground">Last 100 events across all triggers</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 px-6 pt-4 pb-2" role="tablist">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
              tab === t
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
            }`}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Event list */}
      <div className="px-6 pb-6">
        {isLoading && (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
        )}
        {!isLoading && events.length === 0 && (
          <p className="text-sm text-muted-foreground py-8 text-center">No events yet</p>
        )}
        {!isLoading && events.length > 0 && (
          <ul className="space-y-1 mt-2">
            {events.map((evt) => {
              const filePath =
                typeof evt.event_payload.file_path === 'string'
                  ? evt.event_payload.file_path
                  : JSON.stringify(evt.event_payload)
              const isOpen = expanded === evt.id
              return (
                <li key={evt.id}>
                  <button
                    className="w-full text-left px-3 py-2.5 rounded-lg hover:bg-secondary/30 transition-colors flex items-center gap-3"
                    onClick={() => setExpanded(isOpen ? null : evt.id)}
                  >
                    {/* Outcome chip */}
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full shrink-0 ${
                        OUTCOME_CHIP[evt.outcome] ?? 'bg-zinc-500/20 text-zinc-400'
                      }`}
                    >
                      {evt.outcome}
                    </span>
                    {/* File path */}
                    <span className="text-xs text-foreground font-mono truncate flex-1">
                      {filePath.split('/').pop() ?? filePath}
                    </span>
                    {/* Time */}
                    <span className="text-[10px] text-muted-foreground shrink-0">
                      {new Date(evt.fired_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                  </button>

                  {/* Expanded payload */}
                  {isOpen && (
                    <pre className="mx-3 mb-2 p-3 rounded-lg bg-background text-xs text-muted-foreground overflow-auto font-mono">
                      {JSON.stringify(evt, null, 2)}
                    </pre>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
