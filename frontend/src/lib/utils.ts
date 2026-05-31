import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Formats a duration in seconds. By default trailing zero-units are dropped
 * (`60 → "1m"`, `3600 → "1h"`). With `padTrailing: true`, all units down to
 * seconds are always shown (`60 → "1m 0s"`, `3600 → "1h 0m 0s"`) — useful for
 * a live stopwatch where the rightmost unit ticks every second.
 */
export function formatDuration(
  seconds: number,
  opts: { padTrailing?: boolean } = {},
): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60

  if (opts.padTrailing) {
    if (h > 0) return `${h}h ${m}m ${s}s`
    if (m > 0) return `${m}m ${s}s`
    return `${s}s`
  }
  if (total < 60) return `${s}s`
  if (h === 0) return s > 0 ? `${m}m ${s}s` : `${m}m`
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export function basename(filePath: string): string {
  const idx = filePath.lastIndexOf('/')
  return idx === -1 ? filePath : filePath.slice(idx + 1)
}

export function dirname(filePath: string): string {
  const idx = filePath.lastIndexOf('/')
  return idx <= 0 ? '' : filePath.slice(0, idx + 1)
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}
