import { describe, it, expect } from 'vitest'

import { formatVersion } from './version'

describe('formatVersion', () => {
  it('returns the plain semver when no build sha is provided', () => {
    expect(formatVersion('0.2.0')).toBe('0.2.0')
    expect(formatVersion('0.2.0', undefined)).toBe('0.2.0')
  })

  it('treats empty / whitespace sha as no sha', () => {
    expect(formatVersion('0.2.0', '')).toBe('0.2.0')
    expect(formatVersion('0.2.0', '   ')).toBe('0.2.0')
  })

  it('appends the short (7-char) sha as build metadata', () => {
    expect(formatVersion('0.2.0', '48d9549b9b44040762760fe21d3157b4361a03d2')).toBe('0.2.0+48d9549')
  })

  it('keeps an already-short sha intact', () => {
    expect(formatVersion('1.4.2', '48d9549')).toBe('1.4.2+48d9549')
    expect(formatVersion('1.4.2', 'abc')).toBe('1.4.2+abc')
  })

  it('trims surrounding whitespace from the sha', () => {
    expect(formatVersion('0.2.0', '  48d9549b9b44  ')).toBe('0.2.0+48d9549')
  })
})
