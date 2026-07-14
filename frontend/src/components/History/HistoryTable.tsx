import { useState } from 'react'
import { Check, Copy, RotateCcw } from 'lucide-react'
import { useNavigate } from 'react-router'
import ColorPillBadge from '@/components/Queue/ColorPillBadge'
import VerificationBadge from '@/components/Queue/VerificationBadge'
import RowActionsMenu from './RowActionsMenu'
import { basename, formatDuration } from '@/lib/utils'
import { regenerateJob } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import type { HistoryEntry, TerminalStatus } from '@/types/api'

type Props = Readonly<{
  entries: ReadonlyArray<HistoryEntry>
  onDelete: (jobId: string) => void
}>

const STATUS_TO_TOKEN: Record<TerminalStatus, { label: string; cssVar: string }> = {
  completed: { label: 'Done', cssVar: '--phase-done' },
  failed: { label: 'Failed', cssVar: '--phase-failed' },
  cancelled: { label: 'Cancelled', cssVar: '--phase-cancelled' },
}

function formatCost(cost: number | null): string {
  return cost === null ? 'n/a' : `$${cost.toFixed(4)}`
}

function formatTokens(n: number | null): string {
  return n === null ? '—' : n.toLocaleString()
}

function durationLabel(entry: HistoryEntry): string {
  const start = Date.parse(entry.created_at)
  const endRaw = entry.completed_at ?? entry.updated_at
  const end = Date.parse(endRaw)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—'
  return formatDuration((end - start) / 1000)
}

function formatCompletedAt(iso: string | null): string {
  if (iso === null) return '—'
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return iso
  return new Date(ms).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function HistoryTable({ entries, onDelete }: Props) {
  // Lives inside the Recent Executions card, so no own
  // bg/border chrome — just the table.
  return (
    <section aria-label="History entries" className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-border bg-card/60">
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Filename
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Status
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Language
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Model
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider hidden lg:table-cell">
              Provider
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider hidden lg:table-cell">
              Trans. Model
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Tokens
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Cost
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              SRT
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Duration
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Completed
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Verified
            </th>
            <th className="px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wider text-right">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {entries.map((e) => (
            <HistoryRow key={e.id} entry={e} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

type RowProps = Readonly<{
  entry: HistoryEntry
  onDelete: (jobId: string) => void
}>

function HistoryRow({ entry, onDelete }: RowProps) {
  const navigate = useNavigate()
  const status = STATUS_TO_TOKEN[entry.status]
  const isFailed = entry.status === 'failed'

  const langLabel = entry.target_language ?? entry.source_language ?? '—'

  const rowClass = isFailed
    ? 'bg-destructive/5 hover:bg-destructive/10 cursor-pointer transition-colors'
    : 'hover:bg-card/80 cursor-pointer transition-colors'

  // Tooltip carries the error message for failed rows (AC4) — visible to
  // screen readers via title and to mouse users on hover; cheap to render
  // and avoids managing per-row expand state.
  const rowTitle = isFailed && entry.error_message ? entry.error_message : entry.file_path

  return (
    <tr
      onClick={() => navigate(`/jobs/${entry.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate(`/jobs/${entry.id}`)
        }
      }}
      tabIndex={0}
      title={rowTitle}
      className={`${rowClass} h-[44px] focus:outline-none focus:ring-2 focus:ring-primary/50`}
    >
      <td className="px-4 py-2 font-mono text-[13px] text-foreground truncate max-w-[300px]">
        {basename(entry.file_path)}
      </td>
      <td className="px-4 py-2">
        <ColorPillBadge label={status.label} cssVar={status.cssVar} ariaLabel={`Status: ${status.label}`} />
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground">{langLabel}</td>
      <td className="px-4 py-2 text-xs text-muted-foreground">
        {entry.model_size ?? '—'}
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground hidden lg:table-cell">
        {entry.translation_provider ?? '—'}
      </td>
      <td className="px-4 py-2 font-mono text-xs text-muted-foreground hidden lg:table-cell">
        {entry.translation_model ?? '—'}
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground">
        {formatTokens(entry.total_tokens)}
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground">
        {formatCost(entry.cost_usd)}
      </td>
      <td className="px-4 py-2">
        <SrtPathCell entry={entry} />
      </td>
      <td className="px-4 py-2 text-xs text-muted-foreground">{durationLabel(entry)}</td>
      <td className="px-4 py-2 text-xs text-muted-foreground">
        {formatCompletedAt(entry.completed_at ?? entry.updated_at)}
      </td>
      <td className="px-4 py-2">
        <VerificationBadge status={entry.verification_status} score={entry.verification_score} />
      </td>
      <td className="px-4 py-2 text-right">
        <RowActionsMenu jobId={entry.id} onDelete={onDelete} />
      </td>
    </tr>
  )
}

type SrtPathCellProps = Readonly<{ entry: HistoryEntry }>

function SrtPathCell({ entry }: SrtPathCellProps) {
  const [copied, setCopied] = useState(false)
  const path = entry.srt_path

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!path) return
    try {
      await navigator.clipboard.writeText(path)
      setCopied(true)
      globalThis.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard write can fail when the page isn't focused; swallow silently.
    }
  }

  return (
    <div className="flex items-center gap-2 max-w-[260px]">
      {path ? (
        <>
          <span
            className="font-mono text-[11px] text-foreground truncate"
            title={path}
          >
            {basename(path)}
          </span>
          <button
            type="button"
            aria-label={`Copy SRT path for ${basename(entry.file_path)}`}
            onClick={handleCopy}
            className="text-muted-foreground hover:text-foreground transition-colors shrink-0 p-0.5 rounded focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
          </button>
        </>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      )}
      <button
        type="button"
        aria-label={`Regenerate subtitles for ${basename(entry.file_path)}`}
        onClick={(e) => {
          e.stopPropagation()
          void withApiToast(() => regenerateJob(entry.id), { successMessage: 'Regeneration queued' })
        }}
        className="text-muted-foreground hover:text-foreground transition-colors shrink-0 p-0.5 rounded focus:outline-none focus:ring-2 focus:ring-primary/50"
      >
        <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  )
}
