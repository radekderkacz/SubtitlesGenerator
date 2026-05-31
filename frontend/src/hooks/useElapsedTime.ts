import { useEffect, useState } from 'react'
import { formatDuration } from '@/lib/utils'

/**
 * Updates each second while `endISO` is null. Static once `endISO` is set.
 * Returns "Hh Mm Ss" / "Mm Ss" / "Ss" formatted string.
 */
export function useElapsedTime(startISO: string, endISO: string | null): string {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (endISO === null) {
      const id = setInterval(() => setNow(Date.now()), 1000)
      return () => clearInterval(id)
    }
    return undefined
  }, [endISO])

  const startMs = Date.parse(startISO)
  if (!Number.isFinite(startMs)) return '0s'
  const endMs = endISO === null ? now : Date.parse(endISO)
  if (!Number.isFinite(endMs)) return '0s'
  return formatDuration((endMs - startMs) / 1000, { padTrailing: true })
}
