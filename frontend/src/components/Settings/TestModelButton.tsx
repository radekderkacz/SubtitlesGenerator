import { useState } from 'react'
import { CheckCircle2, Loader2, ShieldQuestion, XCircle } from 'lucide-react'
import { ApiRequestError, testTranslationModel } from '@/lib/api'
import type {
  TestTranslationModelPayload,
  TestTranslationModelResponse,
} from '@/lib/api'

type Props = Readonly<{
  /** Live form values from AiBackendsPane. The probe always runs against
   *  the CURRENT field values (not what's been saved), so the user can
   *  test a candidate model before clicking Save. */
  provider: string
  url: string
  model: string
  apiKey: string
  /** Default target language for the translation probe. Polish is the
   *  most-tested target; user can override via Settings later. */
  targetLanguage?: string
  disabled?: boolean
}>

/**
 * "Test this model" button + result card. Runs the same Spider-preservation
 * + glossary-JSON probes that surfaced the gemma3/aya quality gap on
 * 2026-05-15. ~30s round-trip; the result card stays visible until the
 * user dismisses it or runs a new probe.
 *
 * Lives next to the Translation Model field in Settings → AI Backends.
 * Disabled until provider + model are filled in so we don't waste a
 * round-trip on an obviously-incomplete config.
 */
export default function TestModelButton({
  provider,
  url,
  model,
  apiKey,
  targetLanguage = 'pl',
  disabled = false,
}: Props) {
  const [result, setResult] = useState<TestTranslationModelResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const ready = !!provider && !!model.trim() && !disabled

  const onClick = async () => {
    setIsRunning(true)
    setResult(null)
    setError(null)
    const payload: TestTranslationModelPayload = {
      provider,
      model: model.trim(),
      url: url.trim() || undefined,
      api_key: apiKey.trim() || undefined,
      target_language: targetLanguage,
    }
    try {
      const data = await testTranslationModel(payload)
      setResult(data)
    } catch (e) {
      const msg = e instanceof ApiRequestError ? e.message : 'Probe failed'
      setError(msg)
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 mt-1">
      <button
        type="button"
        onClick={onClick}
        disabled={!ready || isRunning}
        className="inline-flex items-center gap-2 self-start text-xs px-3 py-1.5 rounded-md border border-border bg-background hover:bg-card transition-colors disabled:pointer-events-none disabled:opacity-50"
      >
        {isRunning ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        ) : (
          <ShieldQuestion className="h-3 w-3" aria-hidden="true" />
        )}
        {isRunning ? 'Running probes…' : 'Test this model'}
      </button>

      {error && (
        <div role="alert" className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
          <strong className="block mb-1">Probe failed to run</strong>
          {error}
        </div>
      )}

      {result && (
        <TestResultCard result={result} targetLanguage={targetLanguage} />
      )}
    </div>
  )
}

function TestResultCard({
  result,
  targetLanguage,
}: Readonly<{
  result: TestTranslationModelResponse
  targetLanguage: string
}>) {
  // Two binary signals (proper-noun + JSON-glossary) drive the badge.
  // Both pass → green, both fail → red, otherwise → yellow caution.
  const greenCount =
    (result.preserves_proper_nouns ? 1 : 0) + (result.glossary_json_valid ? 1 : 0)
  const bg = pickResultCardBackground(greenCount)

  return (
    <div className={`rounded-md border ${bg} p-3 text-xs space-y-2`}>
      <div className="flex items-center gap-2 font-medium">
        {result.ok ? (
          <>
            <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />
            <span className="text-foreground">Looks good</span>
          </>
        ) : (
          <>
            <XCircle className="h-4 w-4 text-yellow-500" aria-hidden="true" />
            <span className="text-foreground">Caveats — review below</span>
          </>
        )}
      </div>

      <ul className="space-y-1 text-muted-foreground">
        <ResultRow
          label="Preserves proper nouns (e.g. character names)"
          pass={result.preserves_proper_nouns}
        />
        <ResultRow
          label="Glossary returns valid JSON array at long context"
          pass={result.glossary_json_valid}
        />
        {result.sec_per_segment !== null && (
          <li className="flex items-baseline gap-2">
            <span className="text-foreground font-medium">
              {result.sec_per_segment.toFixed(1)}s
            </span>
            <span>per cue (warm — multiply by ~1400 for a feature film)</span>
          </li>
        )}
      </ul>

      {result.sample_translation && (
        <details className="text-muted-foreground">
          <summary className="cursor-pointer text-foreground">
            Sample translation ({targetLanguage})
          </summary>
          <p className="mt-1 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
            {result.sample_translation}
          </p>
        </details>
      )}

      {result.sample_glossary && result.sample_glossary.length > 0 && (
        <details className="text-muted-foreground">
          <summary className="cursor-pointer text-foreground">
            Sample glossary ({result.sample_glossary.length} terms)
          </summary>
          <p className="mt-1 font-mono text-[11px] leading-relaxed">
            {result.sample_glossary.join(', ')}
          </p>
        </details>
      )}
    </div>
  )
}

/** Maps the count of "passing" probe checks (0, 1, or 2) onto the result
 *  card's border + tint. Extracted from a nested ternary inside
 *  TestResultCard to keep that component readable (SonarQube S3358). */
function pickResultCardBackground(passCount: number): string {
  if (passCount === 2) return 'border-emerald-500/40 bg-emerald-500/5'
  if (passCount === 0) return 'border-red-500/40 bg-red-500/5'
  return 'border-yellow-500/40 bg-yellow-500/5'
}

function ResultRow({ label, pass }: Readonly<{ label: string; pass: boolean | null }>) {
  const Icon = pass ? CheckCircle2 : XCircle
  const colour = pass ? 'text-emerald-500' : 'text-red-500'
  return (
    <li className="flex items-baseline gap-2">
      <Icon className={`h-3.5 w-3.5 ${colour} shrink-0 self-center`} aria-hidden="true" />
      <span>{label}</span>
    </li>
  )
}
