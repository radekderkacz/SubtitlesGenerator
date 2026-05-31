/**
 * Curated guidance for the Translation Model picker in Settings → AI Backends.
 *
 * Why this file exists: during the 2026-05-15 model-comparison session a user
 * spent ~3 hours cycling through gpt-oss / aya-expanse / gemma4 / gemma3 to
 * discover that gemma3:27b was the only good fit and aya-expanse silently
 * failed our glossary feature. A first-time user without that context would
 * walk away thinking "the app makes bad subtitles" rather than "I picked the
 * wrong model." This map encodes those findings as inline guidance.
 *
 * Entries are matched against the Ollama/OpenAI model name as a *substring
 * pattern* (case-insensitive); the first match wins. Untagged models fall
 * through to the `unknown` tier.
 */

export type ModelStatus = 'recommended' | 'tested' | 'caution' | 'unsuitable' | 'unknown'

export type ModelGuidance = Readonly<{
  /** Lowercased substring matched against the model name. */
  pattern: string
  status: ModelStatus
  /** Short note (~80 chars) shown as the tag tooltip. */
  note: string
}>

/**
 * Order matters: more specific patterns first. Once a model name matches
 * one pattern the loop stops.
 */
export const TRANSLATION_MODEL_GUIDANCE: readonly ModelGuidance[] = [
  // OpenRouter routes use `provider/model` ids. The hosted Claude family
  // is widely regarded as the strongest LLM for nuanced translation;
  // haven't run our probes against them locally (would burn paid
  // tokens) but the priors are strong enough to mark as tested.
  {
    pattern: 'anthropic/claude',
    status: 'tested',
    note: 'Anthropic Claude via OpenRouter — strong multilingual instruction-following',
  },
  {
    pattern: 'openai/gpt-4',
    status: 'tested',
    note: 'OpenAI GPT-4 family via OpenRouter — reliable translation, paid per-token',
  },
  // Validated 2026-05-15 on Avatar 3 → Polish: extracted 38 proper nouns,
  // 51 min end-to-end, clean Polish, "Spider" preserved everywhere.
  {
    pattern: 'gemma3:27b',
    status: 'recommended',
    note: 'Recommended — proven on Polish/EN, ~2 sec/segment, follows glossary contract',
  },
  // Same family, similar quality, slightly slower:
  {
    pattern: 'gemma3',
    status: 'tested',
    note: 'Google Gemma 3 family — solid multilingual; larger variants run slower',
  },
  // Used for many runs; works but produces over-compressed Polish without
  // the grammar-first prompt rule:
  {
    pattern: 'gpt-oss',
    status: 'tested',
    note: 'Works but English-centric; slower than gemma3 for non-English targets',
  },
  // 2026-05-15 finding: weak instruction-following at long context broke
  // glossary extraction (returned empty []), produced hallucinated Polish
  // words ("zawiady", "atak zatokowy"). The "Spider→pająk" regression
  // returned despite the safety net.
  {
    pattern: 'aya-expanse',
    status: 'caution',
    note: 'Marketed multilingual but fails our glossary extraction at long context',
  },
  {
    pattern: 'aya',
    status: 'caution',
    note: 'Cohere Aya — weak instruction-following at long context (glossary breaks)',
  },
  // Ollama's RENDERER/PARSER integration is unoptimised today — 50 sec/cue
  // vs gemma3's 2 sec/cue. Wait for an Ollama update.
  {
    pattern: 'gemma4',
    status: 'caution',
    note: '~20× slower than gemma3 today (Ollama integration unoptimised)',
  },
  // Reasoning models burn tokens on chain-of-thought — translation is a
  // structured-output task that benefits from suppressing CoT entirely.
  {
    pattern: 'deepseek-r1',
    status: 'unsuitable',
    note: 'Reasoning model — chain-of-thought is wasted on translation, very slow',
  },
  {
    pattern: '-r1',
    status: 'unsuitable',
    note: 'Reasoning model — chain-of-thought wastes tokens on translation',
  },
  // Coder models specialise in code completion and underperform on prose.
  {
    pattern: '-coder',
    status: 'unsuitable',
    note: 'Coding-specialised — produces poorer prose translations',
  },
  {
    pattern: 'coder',
    status: 'unsuitable',
    note: 'Coding-specialised model — poorer prose translation quality',
  },
  // Codestral is Mistral's code model; doesn't share the "coder" substring
  // but lives in the same family of code-specialised tools.
  {
    pattern: 'codestral',
    status: 'unsuitable',
    note: 'Mistral Codestral — code-specialised, poorer prose translation',
  },
  // Embedding models can't even chat — listed so the dropdown explains why.
  {
    pattern: 'embed',
    status: 'unsuitable',
    note: 'Embedding model — does not generate text, cannot translate',
  },
] as const

/**
 * Looks up guidance for a model name. Case-insensitive substring match
 * against the entries above; falls back to ``unknown`` when nothing
 * matches so untested models display a neutral indicator rather than no
 * indicator at all (an empty badge would be silently confusing).
 */
export function getModelGuidance(modelName: string | null | undefined): ModelGuidance {
  if (!modelName) {
    return { pattern: '', status: 'unknown', note: 'Pick a model to see guidance' }
  }
  const needle = modelName.toLowerCase()
  for (const entry of TRANSLATION_MODEL_GUIDANCE) {
    if (needle.includes(entry.pattern.toLowerCase())) return entry
  }
  return {
    pattern: '',
    status: 'unknown',
    note: 'Untested — quality and speed unknown for this app',
  }
}

/**
 * Tailwind class fragments per status — kept here so the badge styling is
 * one source of truth (used by the dropdown row + the "current selection"
 * inline indicator).
 */
export const MODEL_STATUS_STYLES: Record<ModelStatus, { dot: string; label: string }> = {
  recommended: {
    dot: 'bg-emerald-500',
    label: 'Recommended',
  },
  tested: {
    dot: 'bg-sky-500',
    label: 'Tested',
  },
  caution: {
    dot: 'bg-yellow-500',
    label: 'Caution',
  },
  unsuitable: {
    dot: 'bg-red-500',
    label: 'Not recommended',
  },
  unknown: {
    dot: 'bg-muted-foreground/40',
    label: 'Untested',
  },
}
