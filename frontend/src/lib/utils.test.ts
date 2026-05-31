import { describe, it, expect } from 'vitest'
import {
  basename,
  cn,
  dirname,
  formatBytes,
  formatDuration,
} from './utils'

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('handles conditional classes', () => {
    const condition = false
    expect(cn('foo', condition && 'bar', 'baz')).toBe('foo baz')
  })
})

describe('formatDuration', () => {
  it('formats seconds under 60', () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(59)).toBe('59s')
  })

  it('formats minutes', () => {
    expect(formatDuration(60)).toBe('1m')
    expect(formatDuration(90)).toBe('1m 30s')
    expect(formatDuration(3600 - 1)).toBe('59m 59s')
  })

  it('formats hours', () => {
    expect(formatDuration(3600)).toBe('1h')
    expect(formatDuration(3661)).toBe('1h 1m')
    expect(formatDuration(7200)).toBe('2h')
  })
})

describe('formatBytes', () => {
  it('formats bytes', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
  })

  it('formats kilobytes', () => {
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1536)).toBe('1.5 KB')
  })

  it('formats megabytes', () => {
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB')
  })

  it('formats gigabytes', () => {
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.0 GB')
  })
})

describe('formatDuration with padTrailing', () => {
  it('always emits all units down to seconds', () => {
    expect(formatDuration(0, { padTrailing: true })).toBe('0s')
    expect(formatDuration(60, { padTrailing: true })).toBe('1m 0s')
    expect(formatDuration(3600, { padTrailing: true })).toBe('1h 0m 0s')
    expect(formatDuration(3725, { padTrailing: true })).toBe('1h 2m 5s')
  })

  it('floors fractional seconds and clamps negatives', () => {
    expect(formatDuration(5.7)).toBe('5s')
    expect(formatDuration(-10)).toBe('0s')
    expect(formatDuration(-10, { padTrailing: true })).toBe('0s')
  })
})

describe('basename / dirname', () => {
  it('basename strips the directory portion', () => {
    expect(basename('/media/films/Film.mkv')).toBe('Film.mkv')
    expect(basename('Film.mkv')).toBe('Film.mkv')
    expect(basename('/Film.mkv')).toBe('Film.mkv')
    expect(basename('')).toBe('')
  })

  it('dirname returns the directory portion with trailing slash', () => {
    expect(dirname('/media/films/Film.mkv')).toBe('/media/films/')
    expect(dirname('Film.mkv')).toBe('')
    expect(dirname('/Film.mkv')).toBe('')
  })
})

