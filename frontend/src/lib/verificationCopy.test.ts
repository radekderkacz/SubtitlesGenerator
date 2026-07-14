import { describe, it, expect } from 'vitest'
import { badgeLabel, verdictHeadline, issueCopy, formatClock } from './verificationCopy'

describe('badgeLabel', () => {
  it('uses friendly labels and no score', () => {
    expect(badgeLabel('pass')).toBe('Looks good')
    expect(badgeLabel('warn')).toBe('Worth a look')
    expect(badgeLabel('fail')).toBe('Needs attention')
    expect(badgeLabel('running')).toBe('Checking…')
    expect(badgeLabel('error')).toMatch(/couldn.t check/i)
  })
})

describe('verdictHeadline', () => {
  it('pass', () => {
    const h = verdictHeadline('pass', 0)
    expect(h.label).toBe('Looks good'); expect(h.tone).toBe('ok')
  })
  it('warn pluralizes', () => {
    expect(verdictHeadline('warn', 1).summary).toMatch(/1 thing to check/)
    expect(verdictHeadline('warn', 2).summary).toMatch(/2 things to check/)
  })
  it('fail', () => {
    const h = verdictHeadline('fail', 3)
    expect(h.label).toBe('Needs attention'); expect(h.tone).toBe('fail')
    expect(h.summary).toMatch(/3 issues/)
  })
})

describe('formatClock', () => {
  it('formats seconds as m:ss', () => {
    expect(formatClock(2283)).toBe('38:03')
    expect(formatClock(9)).toBe('0:09')
    expect(formatClock(0)).toBe('0:00')
  })
})

describe('issueCopy', () => {
  it('returns null for ok / skipped', () => {
    expect(issueCopy({ layer: 'structural', name: 'coverage', severity: 'ok', detail: '' })).toBeNull()
    expect(issueCopy({ layer: 'semantic', name: 'llm_coherence', severity: 'skipped', detail: '' })).toBeNull()
  })
  it('repeat_loop fail extracts the count and suggests re-generate', () => {
    const c = issueCopy({ layer: 'heuristic', name: 'repeat_loop', severity: 'fail', detail: 'longest identical-line run: 48' })!
    expect(c.title).toMatch(/repeats/i)
    expect(c.explanation).toMatch(/48/)
    expect(c.suggestion).toMatch(/re-generat/i)
  })
  it('reading_speed warn', () => {
    const c = issueCopy({ layer: 'heuristic', name: 'reading_speed', severity: 'warn', detail: '12/386 cues exceed 35.0 cps' })!
    expect(c.title).toMatch(/fast to read/i)
    expect(c.explanation).toMatch(/12/)
  })
  it('coverage fail uses the percentage', () => {
    const c = issueCopy({ layer: 'structural', name: 'coverage', severity: 'fail', detail: 'subtitles cover 12% of runtime' })!
    expect(c.explanation).toMatch(/12%/)
  })
  it('llm_coherence warn shows the score', () => {
    const c = issueCopy({ layer: 'semantic', name: 'llm_coherence', severity: 'warn', detail: 'judge score 60; issues: [...]' })!
    expect(c.explanation).toMatch(/60\/100/)
  })
  it('structural breakage shares one message', () => {
    const c = issueCopy({ layer: 'structural', name: 'non_empty', severity: 'fail', detail: 'SRT file is empty' })!
    expect(c.title).toMatch(/broken/i)
    expect(c.suggestion).toMatch(/re-generate/i)
  })
  it('unknown check name falls back, never blank', () => {
    const c = issueCopy({ layer: 'x', name: 'future_check', severity: 'warn', detail: 'something happened' })!
    expect(c.title.length).toBeGreaterThan(0)
    expect(c.explanation).toBe('something happened')
  })
})
