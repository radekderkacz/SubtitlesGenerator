import { useState } from 'react'
import { Loader2, Send } from 'lucide-react'
import { useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { GenerationControls, controlsBlockedReason, useGenerationControlsState } from '@/components/SubmitSheet/GenerationControls'
import { apiFetch } from '@/lib/api'
import { submitBatch } from './batchSubmit'
import type { FileBrowseEntry, Settings } from '@/types/api'

type Props = Readonly<{
  selectedPaths: ReadonlyArray<string>
  /** Per-path metadata for the `has_srt` skip toggle. */
  fileIndex: ReadonlyMap<string, FileBrowseEntry>
  onCleared: () => void
}>

/**
 * Right-rail aside (xl only) showing batch generation controls alongside the
 * file list. Mirrors the layout of the single-file GenerationPanel aside.
 * Wired into the page layout by Task 3 — this component owns only the
 * controls + submit logic, not its own positioning.
 */
export default function BatchPanel({
  selectedPaths,
  fileIndex,
  onCleared,
}: Props) {
  const navigate = useNavigate()
  const { values, onChange } = useGenerationControlsState()
  const [skipExisting, setSkipExisting] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })

  const profiles = settings?.profiles ?? []

  const eligiblePaths = skipExisting
    ? selectedPaths.filter((p) => !fileIndex.get(p)?.has_srt)
    : [...selectedPaths]
  const skippedCount = selectedPaths.length - eligiblePaths.length
  const blockedReason = controlsBlockedReason(values, profiles.length)

  const handleGenerate = async () => {
    if (blockedReason !== null || eligiblePaths.length === 0) return
    setIsSubmitting(true)
    const n = await submitBatch(eligiblePaths, values)
    setIsSubmitting(false)
    onCleared()
    if (n > 0) navigate('/')
  }

  return (
    <aside
      aria-label="Batch generation settings"
      className="w-[380px] shrink-0 border-l border-border bg-popover hidden xl:flex flex-col min-h-0"
    >
      <header className="p-6 border-b border-border">
        <p className="text-sm font-semibold text-foreground">
          Generate for {selectedPaths.length} file{selectedPaths.length === 1 ? '' : 's'}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        <GenerationControls
          idPrefix="batch"
          values={values}
          profiles={profiles}
          onChange={onChange}
        />

        <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={skipExisting}
            onChange={(e) => setSkipExisting(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          <span>Skip files with SRT</span>
        </label>

        {skipExisting && skippedCount > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer text-amber-500">
              {skippedCount} of {selectedPaths.length} skipped — already have
              subtitles
            </summary>
            <ul className="mt-1 ml-4 list-disc">
              {selectedPaths
                .filter((p) => fileIndex.get(p)?.has_srt)
                .map((p) => (
                  <li key={p} className="font-mono">
                    {p.split('/').pop()}
                  </li>
                ))}
            </ul>
          </details>
        )}

        {blockedReason !== null && (
          <p className="text-xs text-muted-foreground">{blockedReason}</p>
        )}

        <Button
          onClick={handleGenerate}
          disabled={
            isSubmitting ||
            eligiblePaths.length === 0 ||
            blockedReason !== null
          }
          className="w-full gap-2"
        >
          {isSubmitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          Generate {eligiblePaths.length}
        </Button>
      </div>
    </aside>
  )
}
