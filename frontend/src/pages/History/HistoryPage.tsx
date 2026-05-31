import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronLeft, ChevronRight, Coins, Gauge, Languages, Search, Trash2 } from 'lucide-react'
import HistoryTable from '@/components/History/HistoryTable'
import ConfirmDialog from '@/components/ConfirmDialog/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { cancelOrRemoveJob, deleteHistory, listHistory } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import type { HistoryEntry } from '@/types/api'

const PAGE_SIZE = 25

type Props = Readonly<Record<string, never>>

type FilterTab = 'all' | 'completed' | 'failed' | 'cancelled'

const FILTER_TABS: ReadonlyArray<{ key: FilterTab; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'completed', label: 'Done' },
  { key: 'failed', label: 'Failed' },
  { key: 'cancelled', label: 'Cancelled' },
]

function durationSeconds(entry: HistoryEntry): number | null {
  const start = Date.parse(entry.created_at)
  const endRaw = entry.completed_at ?? entry.updated_at
  const end = Date.parse(endRaw)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return Math.max(0, (end - start) / 1000)
}

function formatStat(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—'
  const minutes = Math.round(seconds / 60)
  return `${minutes}m`
}

function topModel(entries: ReadonlyArray<HistoryEntry>): string {
  const counts = new Map<string, number>()
  for (const e of entries) {
    if (!e.model_size) continue
    counts.set(e.model_size, (counts.get(e.model_size) ?? 0) + 1)
  }
  let best: string | null = null
  let max = 0
  for (const [model, count] of counts) {
    if (count > max) {
      best = model
      max = count
    }
  }
  return best ?? '—'
}

export default function HistoryPage(_props: Props) {
  const [filter, setFilter] = useState<FilterTab>('all')
  const [search, setSearch] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [page, setPage] = useState(0)
  const queryClient = useQueryClient()

  // Single round-trip: fetch the unfiltered list and derive counts + filtered
  // view client-side. Cheap relative to four parallel requests, and the
  // backend ordering already returns newest first.
  const query = useQuery({
    queryKey: ['history'],
    queryFn: () => listHistory(),
  })

  // Stable empty-array fallback so the dependent useMemos aren't busted by a
  // fresh `[]` allocation on every render while the query is loading.
  const all = useMemo<ReadonlyArray<HistoryEntry>>(() => query.data ?? [], [query.data])

  const counts = useMemo(() => {
    const c: Record<FilterTab, number> = { all: all.length, completed: 0, failed: 0, cancelled: 0 }
    for (const e of all) {
      c[e.status] += 1
    }
    return c
  }, [all])

  const filtered = useMemo(() => {
    let out = filter === 'all' ? all : all.filter((e) => e.status === filter)
    const q = search.trim().toLowerCase()
    if (q) out = out.filter((e) => e.file_path.toLowerCase().includes(q))
    return out
  }, [all, filter, search])

  // Reset to page 0 whenever the filter / search narrows the result set so
  // we don't end up on a now-empty page.
  useEffect(() => {
    setPage(0)
  }, [filter, search])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageStart = page * PAGE_SIZE
  const pageEnd = Math.min(pageStart + PAGE_SIZE, filtered.length)
  const paged = filtered.slice(pageStart, pageEnd)

  const stats = useMemo(() => {
    const completed = all.filter((e) => e.status === 'completed')
    const failed = all.filter((e) => e.status === 'failed')
    const totalForRate = completed.length + failed.length
    const successRate = totalForRate === 0 ? null : (completed.length / totalForRate) * 100
    const durations = completed.map(durationSeconds).filter((d): d is number => d !== null)
    const avgDuration = durations.length === 0 ? null : durations.reduce((a, b) => a + b, 0) / durations.length
    const totalTokens = all.reduce((s, e) => s + (e.total_tokens ?? 0), 0)
    const totalSpend = all.reduce((s, e) => s + (e.cost_usd ?? 0), 0)
    return {
      successRate,
      avgDuration,
      topModel: topModel(completed),
      totalTokens,
      totalSpend,
    }
  }, [all])

  const handleDeleteEntry = (jobId: string) =>
    withApiToast(() => cancelOrRemoveJob(jobId), {
      successMessage: 'History entry removed',
    }).then(() => {
      queryClient.invalidateQueries({ queryKey: ['history'] }).catch(() => {})
    })

  const handleClearConfirm = () =>
    withApiToast(() => deleteHistory(), {
      successMessage: 'History cleared',
    }).then(() => {
      // invalidateQueries triggers a background refetch; if the refetch itself
      // rejects there's nothing actionable to show — withApiToast already
      // surfaced the delete's outcome.
      queryClient.invalidateQueries({ queryKey: ['history'] }).catch(() => {})
    })

  function renderBody() {
    if (query.isLoading) {
      return (
        <output className="block p-12 text-center text-sm text-muted-foreground">
          Loading history…
        </output>
      )
    }
    if (query.isError) {
      return (
        <output role="alert" className="block p-12 text-center text-sm text-destructive">
          Failed to load history.
        </output>
      )
    }
    if (filtered.length === 0) {
      return (
        <output className="block p-12 text-center text-sm text-muted-foreground">
          {all.length === 0 ? 'No completed jobs yet.' : 'No jobs match the current filter.'}
        </output>
      )
    }
    return <HistoryTable entries={paged} onDelete={handleDeleteEntry} />
  }

  return (
    <div className="max-w-[1280px] mx-auto p-6 space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Job History</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Completed, failed, and cancelled jobs across all watch folders and submissions.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setConfirmOpen(true)}
          disabled={all.length === 0}
          className="gap-2"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
          <span className="text-sm">Clear History</span>
        </Button>
      </header>

      {/* Stats — positioned above the table */}
      <section aria-label="Statistics summary" className="grid grid-cols-1 md:grid-cols-5 gap-6">
        <BentoCard
          icon={<Gauge className="h-5 w-5 text-primary" aria-hidden="true" />}
          eyebrow="Average Speed"
          value={stats.avgDuration === null ? '—' : formatStat(stats.avgDuration)}
          caption="Average completed-job duration"
        />
        <BentoCard
          icon={<CheckCircle2 className="h-5 w-5 text-primary" aria-hidden="true" />}
          eyebrow="Success Rate"
          value={stats.successRate === null ? '—' : `${stats.successRate.toFixed(1)}%`}
          caption="Completed without failure"
        />
        <BentoCard
          icon={<Languages className="h-5 w-5 text-primary" aria-hidden="true" />}
          eyebrow="Top Model"
          value={stats.topModel}
          caption="Used in most completed jobs"
        />
        <BentoCard
          icon={<Coins className="h-5 w-5 text-primary" aria-hidden="true" />}
          eyebrow="Total Tokens"
          value={stats.totalTokens.toLocaleString()}
          caption="Tokens used across all jobs"
        />
        <BentoCard
          icon={<Coins className="h-5 w-5 text-primary" aria-hidden="true" />}
          eyebrow="Total Spend"
          value={`$${stats.totalSpend.toFixed(4)}`}
          caption="Provider-reported only · excludes n/a rows"
        />
      </section>

      {/* Recent Executions card holds the table + its own header (search, tabs) */}
      <div className="bg-card rounded-xl shadow-[0_20px_40px_rgba(0,0,0,0.4)] overflow-hidden">
        <header className="px-6 py-4 flex items-center justify-between gap-4 flex-wrap border-b border-white/[0.05]">
          <h2 className="text-base font-semibold text-foreground">Recent Executions</h2>
          <div className="relative">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search files…"
              aria-label="Search history"
              className="bg-background border-0 text-foreground text-sm rounded-lg pl-9 pr-4 py-1.5 w-64 focus:ring-1 focus:ring-primary outline-none transition-all"
            />
          </div>
        </header>

        <div className="px-6 py-3 flex items-center justify-between flex-wrap gap-4 border-b border-white/[0.02]">
          <div
            role="tablist"
            aria-label="History filter"
            className="inline-flex items-center gap-1 bg-background p-1 rounded-lg"
          >
            {FILTER_TABS.map((tab) => {
              const isActive = filter === tab.key
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setFilter(tab.key)}
                  className={
                    isActive
                      ? 'px-3 py-1 text-xs font-medium rounded bg-secondary text-primary transition-colors'
                      : 'px-3 py-1 text-xs font-medium rounded text-muted-foreground hover:text-foreground transition-colors'
                  }
                >
                  {tab.label} <span className="ml-1 opacity-60">{counts[tab.key]}</span>
                </button>
              )
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            {counts.completed} completed · {counts.failed} failed · {counts.all} total
          </p>
        </div>

        {renderBody()}

        {filtered.length > 0 && (
          <footer className="px-6 py-3 flex items-center justify-between border-t border-white/[0.05] bg-background/40">
            <p className="text-xs text-muted-foreground">
              Showing <span className="font-medium text-foreground">{pageStart + 1}</span> to{' '}
              <span className="font-medium text-foreground">{pageEnd}</span> of{' '}
              <span className="font-medium text-foreground">{filtered.length}</span> entries
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                aria-label="Previous page"
                className="p-1 rounded bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </button>
              <span className="text-xs text-muted-foreground">
                {page + 1} / {pageCount}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                disabled={page >= pageCount - 1}
                aria-label="Next page"
                className="p-1 rounded bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </footer>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Clear job history?"
        description="Active and queued jobs are not affected. This cannot be undone."
        confirmLabel="Clear History"
        onConfirm={handleClearConfirm}
        destructive
      />
    </div>
  )
}

type BentoProps = Readonly<{
  icon: React.ReactNode
  eyebrow: string
  value: string
  caption: string
}>

function BentoCard({ icon, eyebrow, value, caption }: BentoProps) {
  return (
    <div className="bg-card/40 p-6 rounded-xl border border-border flex flex-col justify-between h-40">
      <div className="flex justify-between items-start">
        {icon}
        <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">
          {eyebrow}
        </span>
      </div>
      <div>
        <div className="text-3xl font-bold text-foreground">{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{caption}</p>
      </div>
    </div>
  )
}
