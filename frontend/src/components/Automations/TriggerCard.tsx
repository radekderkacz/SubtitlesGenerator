import { Bolt, Eye, MoreVertical, Play, Trash2 } from 'lucide-react'
import type { Trigger, TriggerType, Schedule, FileFilter } from '@/types/api'
import TriggerTypeIcon from './TriggerTypeIcon'

// Type label map — matched against the design reference
const TYPE_LABEL: Record<TriggerType, string> = {
  watch: 'Watch Folder',
  cron: 'Scheduled',
  webhook: 'Webhook',
}

function scheduleLabel(s: Schedule): string {
  switch (s.mode) {
    case 'hourly':
      return `Every ${s.every_n_hours ?? 1}h`
    case 'daily':
      return `Daily at ${s.time ?? '00:00'}`
    case 'weekly': {
      const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
      return `${days[s.day_of_week ?? 1]} at ${s.time ?? '00:00'}`
    }
    case 'monthly':
      return `Day ${s.day_of_month ?? 1} at ${s.time ?? '00:00'}`
    default:
      return ''
  }
}

function filterLabel(f: FileFilter): string {
  if (f.type === 'all') return 'All video files'
  if (f.type === 'subfolder') return `In ${f.value ?? '…'}`
  if (f.type === 'name_contains') return `Name contains "${f.value ?? ''}"`
  return ''
}

type Props = Readonly<{
  trigger: Trigger
  onEdit?: (trigger: Trigger) => void
  onDelete?: (trigger: Trigger) => void
  onFire?: (trigger: Trigger) => void
  onRevealSecret?: (trigger: Trigger) => void
}>

export default function TriggerCard({
  trigger,
  onEdit,
  onDelete,
  onFire,
  onRevealSecret,
}: Props) {
  const { name, type, enabled, fire_count_24h, last_fired_at } = trigger

  const lastFiredLabel = last_fired_at
    ? new Date(last_fired_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '—'

  return (
    <div
      data-testid="trigger-card"
      className="bg-card rounded-xl p-6 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] border border-white/[0.05] transition-all hover:border-white/10"
    >
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-4">
          <TriggerTypeIcon type={type} />
          <div>
            <h3 className="font-semibold text-lg leading-none text-foreground">{name}</h3>
            <div className="flex items-center gap-2 mt-1.5">
              {enabled ? (
                <>
                  <span className="flex h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-500">
                    Enabled
                  </span>
                </>
              ) : (
                <>
                  <span className="flex h-2 w-2 rounded-full bg-muted-foreground" />
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    Paused
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <button
          className="text-muted-foreground hover:text-foreground p-1.5 rounded"
          aria-label="More options"
          onClick={() => onDelete?.(trigger)}
        >
          <MoreVertical className="h-4 w-4" />
        </button>
      </div>

      {/* Type label + summary */}
      <div className="mb-3 space-y-0.5">
        <p className="text-xs text-muted-foreground">{TYPE_LABEL[type]}</p>
        {type === 'cron' && trigger.config?.schedule != null && (
          <p className="text-xs text-zinc-500 font-mono">
            {scheduleLabel(trigger.config.schedule as unknown as Schedule)}
          </p>
        )}
        {trigger.file_filter && trigger.file_filter.type !== 'all' && (
          <p className="text-xs text-zinc-500">{filterLabel(trigger.file_filter)}</p>
        )}
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground mb-4">
        <span className="flex items-center gap-1.5">
          <Bolt className="h-3.5 w-3.5" aria-hidden />
          fired {fire_count_24h}× in 24h
        </span>
        <span className="flex items-center gap-1.5">
          last {lastFiredLabel}
        </span>
      </div>

      {/* Footer actions */}
      <div className="flex items-center gap-2 pt-4 border-t border-white/5">
        {type === 'webhook' ? (
          <button
            className="text-xs font-semibold px-3 py-1.5 rounded border border-border hover:bg-secondary transition-colors flex items-center gap-1.5"
            aria-label="Reveal secret"
            onClick={() => onRevealSecret?.(trigger)}
          >
            <Eye className="h-3.5 w-3.5" aria-hidden />
            Reveal secret
          </button>
        ) : (
          <button
            className="text-xs font-semibold px-3 py-1.5 rounded border border-border hover:bg-secondary transition-colors flex items-center gap-1.5"
            aria-label="Run now"
            onClick={() => onFire?.(trigger)}
          >
            <Play className="h-3.5 w-3.5" aria-hidden />
            Run now
          </button>
        )}

        <button
          className="text-xs font-semibold px-3 py-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
          onClick={() => onEdit?.(trigger)}
        >
          Edit
        </button>

        <button
          className="ml-auto text-muted-foreground hover:text-destructive p-1.5 rounded"
          aria-label="Delete trigger"
          onClick={() => onDelete?.(trigger)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
