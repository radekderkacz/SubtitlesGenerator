import { describe, it, expect } from 'vitest'
import { getModelGuidance, MODEL_STATUS_STYLES } from './translation-models'

describe('getModelGuidance', () => {
  it('flags gemma3:27b as the Recommended default', () => {
    // The specific tag the user is steered toward as of 2026-05-15. The
    // note text intentionally includes "Recommended" so the UI can use
    // the note as a screen-reader-friendly tooltip.
    const g = getModelGuidance('gemma3:27b')
    expect(g.status).toBe('recommended')
    expect(g.note.toLowerCase()).toContain('recommend')
  })

  it('falls back to the gemma3 family entry for smaller Gemma 3 tags', () => {
    // The specific gemma3:27b entry must lose to the family-wide gemma3
    // entry only when no exact match — but the family entry is `tested`
    // not `recommended`. We test that the LIST ORDER (specific → family)
    // is respected: `gemma3:27b` resolves to recommended, `gemma3:12b`
    // resolves to the family tier.
    expect(getModelGuidance('gemma3:27b').status).toBe('recommended')
    expect(getModelGuidance('gemma3:12b').status).toBe('tested')
  })

  it('flags aya-expanse:* and bare aya as caution', () => {
    // The 2026-05-15 finding that motivated this map — Aya silently fails
    // glossary extraction at long context. The user reads the note text
    // *while picking*, so it must name the specific failure mode.
    const expanse = getModelGuidance('aya-expanse:32b')
    expect(expanse.status).toBe('caution')
    expect(expanse.note.toLowerCase()).toContain('glossary')

    expect(getModelGuidance('aya:35b').status).toBe('caution')
  })

  it('flags gemma4 as caution (slow integration, not bad quality)', () => {
    // Distinct from aya's caution — gemma4's caveat is *performance*, not
    // quality. The note should make that distinction so a user with
    // patience can still choose it knowingly.
    const g = getModelGuidance('gemma4:26b')
    expect(g.status).toBe('caution')
    expect(g.note.toLowerCase()).toMatch(/slow|sec\/cue/)
  })

  it('flags deepseek-r1 and other reasoning models as unsuitable', () => {
    expect(getModelGuidance('deepseek-r1:32b').status).toBe('unsuitable')
    // The `-r1` substring catches future reasoning variants without us
    // needing to add an entry for every new release (qwen-r1, llama-r1…).
    expect(getModelGuidance('some-fancy-r1:8b').status).toBe('unsuitable')
  })

  it('flags coder-specialised models as unsuitable for translation', () => {
    expect(getModelGuidance('qwen3-coder-next:79b').status).toBe('unsuitable')
    expect(getModelGuidance('codestral:22b').status).toBe('unsuitable')
  })

  it('flags embedding models as unsuitable', () => {
    // Embeddings can't even generate text — listing them prevents the
    // confusing failure mode where a user picks them and gets empty
    // translations with no error.
    expect(getModelGuidance('mxbai-embed-large:latest').status).toBe('unsuitable')
    expect(getModelGuidance('nomic-embed-text').status).toBe('unsuitable')
  })

  it('returns unknown for an untested model name', () => {
    // Falls back to a neutral state — better than a missing badge (which
    // would silently suggest the model is fine).
    const g = getModelGuidance('some-fictional-model:7b')
    expect(g.status).toBe('unknown')
    expect(g.note.toLowerCase()).toContain('untested')
  })

  it('handles empty / null / undefined model name gracefully', () => {
    expect(getModelGuidance('').status).toBe('unknown')
    expect(getModelGuidance(null).status).toBe('unknown')
    expect(getModelGuidance(undefined).status).toBe('unknown')
  })

  it('is case-insensitive', () => {
    expect(getModelGuidance('GEMMA3:27b').status).toBe('recommended')
    expect(getModelGuidance('AYA-EXPANSE:32B').status).toBe('caution')
  })
})

describe('MODEL_STATUS_STYLES', () => {
  it('provides a dot colour + label for every ModelStatus', () => {
    // Compile-time check: TypeScript already enforces the Record<>, but
    // running the assertion at test time catches an accidental partial
    // override (e.g. a future contributor adds a new status to the type
    // but forgets to add its style here, expanding the Record's keys
    // implicitly).
    for (const status of ['recommended', 'tested', 'caution', 'unsuitable', 'unknown'] as const) {
      expect(MODEL_STATUS_STYLES[status].dot).toBeTruthy()
      expect(MODEL_STATUS_STYLES[status].label).toBeTruthy()
    }
  })
})
