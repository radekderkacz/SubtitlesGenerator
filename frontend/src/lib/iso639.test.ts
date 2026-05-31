import { describe, expect, it } from 'vitest'
import { AUTO_DETECT, LANGUAGES, filterLanguages, findLanguage } from './iso639'

describe('iso639', () => {
  it('LANGUAGES is non-empty and alphabetised by English name', () => {
    expect(LANGUAGES.length).toBeGreaterThan(20)
    const englishNames = LANGUAGES.map((l) => l.english)
    const sorted = [...englishNames].sort((a, b) => a.localeCompare(b))
    expect(englishNames).toEqual(sorted)
  })

  it('every entry has a non-empty code, native, and english name', () => {
    for (const l of LANGUAGES) {
      expect(l.code).toMatch(/^[a-z]{2}$/)
      expect(l.native.length).toBeGreaterThan(0)
      expect(l.english.length).toBeGreaterThan(0)
    }
  })

  it('AUTO_DETECT has code "auto" and is not in LANGUAGES', () => {
    expect(AUTO_DETECT.code).toBe('auto')
    expect(LANGUAGES.find((l) => l.code === 'auto')).toBeUndefined()
  })

  describe('findLanguage', () => {
    it('returns the matching entry for a known code', () => {
      expect(findLanguage('en')?.english).toBe('English')
      expect(findLanguage('ja')?.native).toBe('日本語')
    })
    it('returns AUTO_DETECT for "auto"', () => {
      expect(findLanguage('auto')).toBe(AUTO_DETECT)
    })
    it('returns null for an unknown code', () => {
      expect(findLanguage('zz')).toBeNull()
    })
  })

  describe('filterLanguages', () => {
    it('returns the full list when the query is empty', () => {
      expect(filterLanguages('').length).toBe(LANGUAGES.length)
      expect(filterLanguages('   ').length).toBe(LANGUAGES.length)
    })
    it('matches by English name (case-insensitive)', () => {
      const result = filterLanguages('FRENCH')
      expect(result.map((l) => l.code)).toContain('fr')
    })
    it('matches by native name', () => {
      const result = filterLanguages('日本語')
      expect(result.map((l) => l.code)).toEqual(['ja'])
    })
    it('matches by code', () => {
      const result = filterLanguages('zh')
      expect(result.map((l) => l.code)).toContain('zh')
    })
    it('returns empty array on no match', () => {
      expect(filterLanguages('xyzabc')).toEqual([])
    })
  })
})
