import { useMemo } from 'react'
import { Download } from 'lucide-react'
import type { Job, JobStatus, JobPhase } from '@/types/api'

// Construct the download URL inline rather than importing the helper from
// @/lib/api — the existing test mocks of that module don't spread the
// original exports, so a new helper would force every callsite's mock to
// be updated. The URL has only one shape; inlining it costs nothing.
function downloadHref(jobId: string): string {
  return `/api/v1/history/${encodeURIComponent(jobId)}/log`
}

type Props = Readonly<{
  job: Job
  /**
   * Raw log file content (text/plain from `/api/v1/history/:id/log`). When
   * provided, parsed and rendered line-by-line. Omit on QueuePage where no
   * persistent log endpoint is available for in-flight jobs and we fall back
   * to synthetic phase-based lines.
   */
  rawLog?: string
}>

type LogLine = Readonly<{
  ts: string
  message: string
  tone: 'mute' | 'amber' | 'blue' | 'violet' | 'cyan' | 'emerald' | 'red'
}>

const TONE_TO_COLOR_VAR: Record<LogLine['tone'], string | null> = {
  mute: null,
  amber: '--phase-extracting',
  blue: '--phase-transcribing',
  violet: '--phase-translating',
  cyan: '--phase-writing',
  emerald: '--phase-done',
  red: '--phase-failed',
}

const PHASE_TONE: Record<NonNullable<JobPhase>, LogLine['tone']> = {
  extracting: 'amber',
  transcribing: 'blue',
  translating: 'violet',
  writing: 'cyan',
  done: 'emerald',
}

function formatTs(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--:--:--'
  return d.toTimeString().slice(0, 8)
}

function shiftSeconds(iso: string, sec: number): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Date(d.getTime() + sec * 1000).toISOString()
}

function generateLines(job: Job): ReadonlyArray<LogLine> {
  const start = job.created_at
  const lines: LogLine[] = [
    {
      ts: formatTs(start),
      message: `Job received. Initializing pipeline for ID: ${job.id.slice(0, 8)}…`,
      tone: 'mute',
    },
  ]

  const reachedExtracting = phaseReached(job.status, job.phase, 'extracting')
  const reachedTranscribing = phaseReached(job.status, job.phase, 'transcribing')
  const reachedTranslating = phaseReached(job.status, job.phase, 'translating')
  const reachedWriting = phaseReached(job.status, job.phase, 'writing')
  const reachedDone = job.status === 'completed'

  if (reachedExtracting) {
    lines.push({
      ts: formatTs(shiftSeconds(start, 5)),
      message: 'Extracting audio stream from container with ffmpeg…',
      tone: 'amber',
    })
  }
  if (reachedTranscribing) {
    lines.push(
      {
        ts: formatTs(shiftSeconds(start, 18)),
        message: 'Audio extraction complete. Temporary WAV created.',
        tone: 'emerald',
      },
      {
        ts: formatTs(shiftSeconds(start, 22)),
        message: `Loading Whisper ${job.model_size ?? 'large-v3'} model into VRAM…`,
        tone: 'blue',
      },
      {
        ts: formatTs(shiftSeconds(start, 28)),
        message: 'Transcription started. Streaming segments…',
        tone: 'mute',
      },
    )
  }
  if (reachedTranslating) {
    lines.push(
      {
        ts: formatTs(shiftSeconds(start, 200)),
        message: `Transcription complete. Detected language: ${job.source_language ?? '—'}`,
        tone: 'blue',
      },
      {
        ts: formatTs(shiftSeconds(start, 215)),
        message: `Starting translation to ${job.target_language ?? 'target'}…`,
        tone: 'violet',
      },
    )
  }
  if (reachedWriting) {
    lines.push(
      {
        ts: formatTs(shiftSeconds(start, 360)),
        message: 'Translation complete. Mapping strings to original timestamps.',
        tone: 'violet',
      },
      {
        ts: formatTs(shiftSeconds(start, 380)),
        message: 'Writing SRT file to media directory…',
        tone: 'cyan',
      },
    )
  }
  if (reachedDone) {
    const finishedAt = job.completed_at ?? job.updated_at
    lines.push({
      ts: formatTs(finishedAt),
      message: 'Job finished successfully.',
      tone: 'emerald',
    })
  }
  if (job.status === 'failed') {
    lines.push({
      ts: formatTs(job.updated_at),
      message: job.error_message ?? 'Pipeline failed. See details.',
      tone: 'red',
    })
  }
  if (job.status === 'cancelled') {
    lines.push({
      ts: formatTs(job.updated_at),
      message: 'Job cancelled by user.',
      tone: 'mute',
    })
  }
  return lines
}

const PHASE_ORDER = ['extracting', 'transcribing', 'translating', 'writing', 'done'] as const

function phaseReached(
  status: JobStatus,
  phase: JobPhase | null,
  target: NonNullable<JobPhase>,
): boolean {
  if (status === 'completed') return true
  if (status === 'queued' || phase === null) return false
  return PHASE_ORDER.indexOf(phase) >= PHASE_ORDER.indexOf(target)
}

// Worker writes log lines as `<ISO8601> <LEVEL> [job:<id>] <message>` with
// single-space separators (level is fixed-width 5: `INFO `, `WARN `, etc.).
// Parse by splitting on whitespace rather than regex to avoid the linear-
// runtime concern SonarQube raises around backtracking patterns.
const KNOWN_LEVELS: ReadonlySet<string> = new Set(['INFO', 'WARN', 'ERROR', 'DEBUG'])

function parseLogLine(line: string): LogLine | null {
  const firstSpace = line.indexOf(' ')
  if (firstSpace < 0) return null
  const iso = line.slice(0, firstSpace)
  const rest = line.slice(firstSpace + 1).trimStart()
  // After the timestamp the level word ends at the next whitespace.
  const secondSpace = rest.indexOf(' ')
  if (secondSpace < 0) return null
  const level = rest.slice(0, secondSpace).trim()
  if (!KNOWN_LEVELS.has(level)) return null
  // Skip the `[job:<id>]` segment if present, keep everything else as message.
  const tail = rest.slice(secondSpace + 1).trimStart()
  const messageStart = tail.startsWith('[job:') ? tail.indexOf(']') + 1 : 0
  const message = tail.slice(messageStart).trimStart()
  return { ts: formatTs(iso), message, tone: toneForLevel(level, message) }
}

function parseRawLog(rawLog: string): ReadonlyArray<LogLine> {
  const out: LogLine[] = []
  for (const line of rawLog.split('\n')) {
    if (!line.trim()) continue
    const parsed = parseLogLine(line)
    out.push(parsed ?? { ts: '--:--:--', message: line, tone: 'mute' })
  }
  return out
}

function toneForLevel(level: string, message: string): LogLine['tone'] {
  if (level === 'ERROR') return 'red'
  if (level === 'WARN') return 'amber'
  // INFO/DEBUG — colour-hint by phase keyword in the message so the log
  // visually mirrors PhaseTimeline.
  const m = message.toLowerCase()
  if (m.includes('extract')) return 'amber'
  if (m.includes('transcrib') || m.includes('whisper')) return 'blue'
  if (m.includes('translat')) return 'violet'
  if (m.includes('writ') && m.includes('srt')) return 'cyan'
  if (m.includes('complet') || m.includes('finished')) return 'emerald'
  return 'mute'
}

export default function LiveLogPane({ job, rawLog }: Props) {
  const lines = useMemo(
    () => (rawLog === undefined ? generateLines(job) : parseRawLog(rawLog)),
    [job, rawLog],
  )
  const isActive = rawLog === undefined && job.status === 'processing'
  const cursorTone: LogLine['tone'] = job.phase ? PHASE_TONE[job.phase] : 'blue'
  const cursorVar = TONE_TO_COLOR_VAR[cursorTone]
  return (
    <section
      aria-label="Live log"
      className="bg-card border border-border rounded-lg flex flex-col h-full min-h-[300px] overflow-hidden"
    >
      <header className="px-6 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-widest">
          Live Log Output
        </h3>
        <a
          href={downloadHref(job.id)}
          download={`${job.id}.log`}
          className="text-xs text-primary hover:underline flex items-center gap-1.5"
        >
          <Download className="h-3.5 w-3.5" aria-hidden="true" />
          Download Full Log
        </a>
      </header>
      <div className="bg-background p-5 font-mono text-[12px] leading-relaxed flex-1 overflow-y-auto">
        {lines.length === 0 ? (
          <p className="text-muted-foreground italic">No log content available yet.</p>
        ) : (
          lines.map((line, i) => (
            <div key={`${line.ts}-${i}`} className="flex gap-4">
              <span className="text-muted-foreground/60 shrink-0">[{line.ts}]</span>
              <span style={cssColorForTone(line.tone)} className={classForTone(line.tone)}>
                {line.message}
              </span>
            </div>
          ))
        )}
        {isActive && (
          <div className="mt-3 animate-pulse" style={cursorVar ? { color: `var(${cursorVar})` } : undefined}>
            _
          </div>
        )}
      </div>
    </section>
  )
}

function cssColorForTone(tone: LogLine['tone']): React.CSSProperties | undefined {
  const v = TONE_TO_COLOR_VAR[tone]
  return v === null ? undefined : { color: `var(${v})` }
}

function classForTone(tone: LogLine['tone']): string {
  if (tone === 'mute') return 'text-muted-foreground'
  return ''
}
