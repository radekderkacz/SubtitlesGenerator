import type { VerificationStatus } from '@/types/api'

export type Check = {
  layer: string; name: string; severity: string; detail: string
  repeated?: { text: string; start: number; end: number; count: number }
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
export type IssueCopy = { title: string; explanation: string; suggestion: string }
export type Tone = 'ok' | 'warn' | 'fail' | 'neutral'
export type Headline = { label: string; summary: string; tone: Tone }

export function badgeLabel(status: VerificationStatus): string {
  switch (status) {
    case 'running':
      return 'Checking…'
    case 'pass':
      return 'Looks good'
    case 'warn':
      return 'Worth a look'
    case 'fail':
      return 'Needs attention'
    case 'skipped':
      return 'Not checked'
    case 'error':
      return 'Couldn’t check'
    default:
      return 'Checked'
  }
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

export function verdictHeadline(status: VerificationStatus | null, issueCount: number): Headline {
  switch (status) {
    case 'pass':
      return { label: 'Looks good', summary: 'These subtitles passed every check.', tone: 'ok' }
    case 'warn':
      return { label: 'Worth a look', summary: `${plural(issueCount, 'thing', 'things')} to check, nothing broken.`, tone: 'warn' }
    case 'fail':
      return { label: 'Needs attention', summary: `${plural(issueCount, 'issue', 'issues')} that may need a re-generate.`, tone: 'fail' }
    case 'running':
      return { label: 'Checking subtitles…', summary: '', tone: 'neutral' }
    case 'error':
      return { label: 'Couldn’t run the check', summary: 'This doesn’t affect your subtitles.', tone: 'neutral' }
    default:
      return { label: 'Not checked yet', summary: '', tone: 'neutral' }
  }
}

// The metric we want is always the first integer in the detail string (run
// count / percentage / cue count / score all lead). A single bounded `\d+` is
// linear — no backtracking — so no ReDoS surface.
const DIGITS = /\d+/
function firstInt(detail: string): string | null {
  const m = DIGITS.exec(detail)
  return m ? m[0] : null
}

function repeatCopy(sev: string, detail: string): IssueCopy {
  const n = firstInt(detail) ?? 'many'
  if (sev === 'fail') {
    return {
      title: 'A line repeats over and over',
      explanation: `One line repeats about ${n} times in a row — usually a transcription glitch on music or silence.`,
      suggestion: 'Re-generating these subtitles usually clears it.',
    }
  }
  return {
    title: 'Some repeated lines',
    explanation: `A line repeats about ${n} times in a row. Often this is real (a chant or repeated shout), but it can be a transcription hiccup.`,
    suggestion: 'Worth a quick listen to that part; re-generate if it looks wrong.',
  }
}

function coverageCopy(sev: string, detail: string): IssueCopy {
  const p = firstInt(detail) ?? 'part of'
  if (sev === 'fail') {
    return {
      title: 'Most of the video has no subtitles',
      explanation: `Subtitles cover only about ${p}% of the runtime — transcription likely stopped early.`,
      suggestion: 'Re-generate these subtitles.',
    }
  }
  return {
    title: 'Subtitles cover only part of the video',
    explanation: `About ${p}% of the runtime has subtitles.`,
    suggestion: 'If the rest has dialogue, re-generate; if it’s a silent or action stretch, it’s fine.',
  }
}

function coherenceCopy(sev: string, detail: string): IssueCopy {
  const n = firstInt(detail)
  const score = n ? ` (${n}/100)` : ''
  if (sev === 'fail') {
    return {
      title: 'Wording reads poorly',
      explanation: `An automated language check rated the wording low${score} — parts may read awkwardly or not make sense.`,
      suggestion: 'Re-generating, or trying a different translation model, may help.',
    }
  }
  return {
    title: 'Wording could be better',
    explanation: `An automated language check flagged a few awkward spots${score}.`,
    suggestion: 'Usually fine — glance at the flagged lines.',
  }
}

const BROKEN: IssueCopy = {
  title: 'These subtitles look broken',
  explanation: 'The file is empty, has almost no lines, or has invalid timing.',
  suggestion: 'Re-generate these subtitles.',
}

export function issueCopy(check: Check): IssueCopy | null {
  if (check.severity !== 'warn' && check.severity !== 'fail') return null
  const d = check.detail || ''
  switch (check.name) {
    case 'repeat_loop':
      return repeatCopy(check.severity, d)
    case 'coverage':
      return coverageCopy(check.severity, d)
    case 'llm_coherence':
      return coherenceCopy(check.severity, d)
    case 'reading_speed':
      return {
        title: 'Some lines may be fast to read',
        explanation: `About ${firstInt(d) ?? 'some'} lines show only briefly for how much text they contain, so they may be hard to read in time.`,
        suggestion: 'Usually still watchable — check that stretch if it bothers you.',
      }
    case 'no_overlap':
      return {
        title: 'Some subtitles overlap on screen',
        explanation: 'Several lines briefly appear at the same time as the next one.',
        suggestion: 'Minor — usually still readable.',
      }
    case 'artifact_phrase':
      return {
        title: 'Possible junk text',
        explanation: 'Found phrases that are often transcription noise (e.g. "thanks for watching", "subtitles by…").',
        suggestion: 'Skim the subtitles for stray lines that don’t belong; remove or re-generate if present.',
      }
    case 'loop_vocabulary':
      return {
        title: 'A stretch keeps cycling the same few lines',
        explanation: 'Dozens of consecutive subtitles draw on only two or three distinct lines — a classic transcription loop on music or silence.',
        suggestion: 'Re-generating these subtitles usually clears it.',
      }
    case 'alignment':
      return {
        title: 'Translation length looks off',
        explanation: `The translated file has a very different amount of text than the original (${d}).`,
        suggestion: 'Some lines may have been dropped or duplicated — re-generate if the subtitles feel incomplete.',
      }
    case 'blank_cues':
      return {
        title: 'Some subtitles are empty',
        explanation: `A noticeable share of entries contain no text (${d}).`,
        suggestion: 'Re-generate these subtitles.',
      }
    case 'monotonic_order':
      return {
        title: 'Subtitles are out of order',
        explanation: 'Some entries start earlier than the ones before them — players may show them erratically.',
        suggestion: 'Re-generate these subtitles.',
      }
    case 'line_length':
      return {
        title: 'Some lines are very long',
        explanation: `A share of lines exceed the comfortable on-screen width (${d}).`,
        suggestion: 'Usually still watchable — mostly affects small screens.',
      }
    case 'output_language':
      return {
        title: 'Subtitles look like the wrong language',
        explanation: d || 'The finished file reads as a different language than requested — the translation likely failed.',
        suggestion: 'Re-generate these subtitles; check the translation model settings if it repeats.',
      }
    case 'av_sync':
      return {
        title: 'Timing looks shifted against the audio',
        explanation: d || 'The subtitles appear consistently earlier or later than the detected speech.',
        suggestion: 'Re-generate; if it persists, the video may have an unusual audio track layout.',
      }
    case 'non_empty':
    case 'min_cues':
    case 'start_before_end':
      return BROKEN
    default:
      return { title: 'Quality note', explanation: d || 'See details below.', suggestion: '' }
  }
}
