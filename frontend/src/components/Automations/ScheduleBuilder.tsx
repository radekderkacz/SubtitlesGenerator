import { useState, useEffect, useCallback } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { previewCron } from '@/lib/api'
import type { Schedule } from '@/types/api'

type Props = Readonly<{
  value: Schedule
  onChange: (s: Schedule) => void
}>

const HOUR_OPTIONS = [1, 2, 3, 4, 6, 8, 12]
const DAY_OF_WEEK_OPTIONS = [
  { label: 'Sunday', value: 0 },
  { label: 'Monday', value: 1 },
  { label: 'Tuesday', value: 2 },
  { label: 'Wednesday', value: 3 },
  { label: 'Thursday', value: 4 },
  { label: 'Friday', value: 5 },
  { label: 'Saturday', value: 6 },
]
const DAY_OF_MONTH_OPTIONS = Array.from({ length: 28 }, (_, i) => i + 1)

function scheduleToSummary(s: Schedule): string {
  switch (s.mode) {
    case 'hourly':
      return `Runs every ${s.every_n_hours ?? 1} hour${(s.every_n_hours ?? 1) > 1 ? 's' : ''}`
    case 'daily':
      return `Runs daily at ${s.time ?? '00:00'}`
    case 'weekly': {
      const day = DAY_OF_WEEK_OPTIONS.find((d) => d.value === s.day_of_week)?.label ?? 'Sunday'
      return `Runs every ${day} at ${s.time ?? '00:00'}`
    }
    case 'monthly':
      return `Runs on day ${s.day_of_month ?? 1} of every month at ${s.time ?? '00:00'}`
    default:
      return ''
  }
}

export default function ScheduleBuilder({ value, onChange }: Props) {
  const [nextFires, setNextFires] = useState<string[]>([])

  const fetchPreview = useCallback(async (s: Schedule) => {
    try {
      const res = await previewCron(s, 3)
      setNextFires(res.next_fires ?? [])
    } catch {
      setNextFires([])
    }
  }, [])

  useEffect(() => {
    const t = setTimeout(() => { fetchPreview(value) }, 600)
    return () => clearTimeout(t)
  }, [value, fetchPreview])

  const handleModeChange = (mode: string | null) => {
    if (!mode) return
    const base = { mode: mode as Schedule['mode'] }
    if (mode === 'hourly') onChange({ ...base, every_n_hours: 1 })
    else if (mode === 'daily') onChange({ ...base, time: '03:00' })
    else if (mode === 'weekly') onChange({ ...base, day_of_week: 1, time: '03:00' })
    else if (mode === 'monthly') onChange({ ...base, day_of_month: 1, time: '03:00' })
  }

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="space-y-2">
        <Label className="text-sm font-medium text-zinc-400 uppercase tracking-wider">Schedule</Label>
        <Select value={value.mode} onValueChange={handleModeChange}>
          <SelectTrigger className="h-12 w-full bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hourly">Hourly</SelectItem>
            <SelectItem value="daily">Daily</SelectItem>
            <SelectItem value="weekly">Weekly</SelectItem>
            <SelectItem value="monthly">Monthly</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Mode-specific controls */}
      {value.mode === 'hourly' && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-zinc-400">Every</span>
          <Select
            value={String(value.every_n_hours ?? 1)}
            onValueChange={(v) => { if (v) onChange({ ...value, every_n_hours: Number.parseInt(v, 10) }) }}
          >
            <SelectTrigger className="w-24 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {HOUR_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>{n}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-zinc-400">hours</span>
        </div>
      )}

      {value.mode === 'daily' && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-zinc-400">At</span>
          <Input
            type="time"
            value={value.time ?? '03:00'}
            onChange={(e) => onChange({ ...value, time: e.target.value })}
            className="w-32 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg"
          />
        </div>
      )}

      {value.mode === 'weekly' && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-zinc-400">Every</span>
          <Select
            value={String(value.day_of_week ?? 1)}
            onValueChange={(v) => { if (v) onChange({ ...value, day_of_week: Number.parseInt(v, 10) }) }}
          >
            <SelectTrigger className="w-36 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAY_OF_WEEK_OPTIONS.map((d) => (
                <SelectItem key={d.value} value={String(d.value)}>{d.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-zinc-400">at</span>
          <Input
            type="time"
            value={value.time ?? '03:00'}
            onChange={(e) => onChange({ ...value, time: e.target.value })}
            className="w-32 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg"
          />
        </div>
      )}

      {value.mode === 'monthly' && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-zinc-400">On day</span>
          <Select
            value={String(value.day_of_month ?? 1)}
            onValueChange={(v) => { if (v) onChange({ ...value, day_of_month: Number.parseInt(v, 10) }) }}
          >
            <SelectTrigger className="w-20 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAY_OF_MONTH_OPTIONS.map((d) => (
                <SelectItem key={d} value={String(d)}>{d}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-zinc-400">at</span>
          <Input
            type="time"
            value={value.time ?? '03:00'}
            onChange={(e) => onChange({ ...value, time: e.target.value })}
            className="w-32 h-10 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg"
          />
        </div>
      )}

      {/* Plain-English summary */}
      <p className="text-xs text-zinc-400 bg-blue-500/5 border border-blue-500/10 px-4 py-3 rounded-lg">
        {scheduleToSummary(value)}
      </p>

      {/* Next 3 runs */}
      {nextFires.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] text-zinc-400 font-semibold uppercase tracking-wider">Next 3 runs</p>
          <div className="flex flex-wrap gap-2">
            {nextFires.map((ts) => (
              <span
                key={ts}
                className="px-2 py-1 bg-zinc-800 text-[10px] text-zinc-400 rounded-full font-medium"
              >
                {new Date(ts).toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
