/** Collapsible explainer above the Translation Engine settings —
 *  surfaces the heuristics that took the 2026-05-15 model-comparison
 *  session to discover (bigger != better, multilingual training matters,
 *  reasoning models are slow). Uses <details>/<summary> so it's
 *  zero-JS, keyboard-accessible, and respects the user's prefers-reduced-
 *  motion. */
export default function ModelGuidanceHelp() {
  return (
    <details className="rounded-md border border-border bg-background/50 px-3 py-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none text-foreground font-medium">
        How to pick a translation model
      </summary>
      <div className="mt-2 space-y-2 leading-relaxed">
        <p>
          Bigger isn&apos;t always better. For subtitle translation the model needs to
          (a) follow strict output formatting, (b) be trained on the target language,
          and (c) generate quickly enough to finish a feature-length film without
          you giving up.
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <strong className="text-foreground">Multilingual {'>'} general.</strong>{' '}
            Models trained heavily on European languages (Gemma 3, Mistral)
            outperform English-centric ones (gpt-oss) on Polish, German, French.
          </li>
          <li>
            <strong className="text-foreground">Avoid reasoning models.</strong>{' '}
            DeepSeek-R1 and similar burn most of their tokens on chain-of-thought,
            which translation doesn&apos;t need. They&apos;re slow and produce less
            accurate translations.
          </li>
          <li>
            <strong className="text-foreground">Avoid code models.</strong>{' '}
            Anything with &quot;coder&quot;, &quot;codestral&quot; in the name is
            tuned for source code, not prose.
          </li>
          <li>
            <strong className="text-foreground">Watch the per-segment latency.</strong>{' '}
            A 1.5h film has ~1,400 cues; at 5 sec/cue that&apos;s 2 hours of
            translation alone. The badges next to each model encode our measured
            findings.
          </li>
        </ul>
        <p>
          The dots beside each model in the dropdown above encode our 2026-05-15
          measurements:{' '}
          <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 align-middle" />{' '}
          recommended,{' '}
          <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-sky-500 align-middle" />{' '}
          tested,{' '}
          <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-yellow-500 align-middle" />{' '}
          caution,{' '}
          <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-red-500 align-middle" />{' '}
          not recommended.
        </p>
      </div>
    </details>
  )
}
