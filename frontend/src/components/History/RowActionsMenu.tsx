import { useEffect, useRef, useState } from 'react'
import { Download, MoreVertical, Trash2 } from 'lucide-react'
import { downloadJobLogUrl } from '@/lib/api'

type Props = Readonly<{
  jobId: string
  /** Called when the user picks the destructive Delete option. */
  onDelete: (jobId: string) => void
}>

/**
 * Compact row-level overflow menu used by the History table's Actions
 * column. Toggles open on the ⋮ button click, dismisses on click-outside
 * or Escape. The ⋮ button stops propagation so opening the menu doesn't
 * also fire the row-level navigation handler.
 */
export default function RowActionsMenu({ jobId, onDelete }: Props) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={containerRef} className="relative inline-flex">
      <button
        type="button"
        aria-label="Row actions"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        className="p-1 text-muted-foreground hover:text-primary transition-colors rounded"
      >
        <MoreVertical className="h-4 w-4" aria-hidden="true" />
      </button>
      {open && (
        // No `role="menu"` — the items themselves are real anchors/buttons
        // so AT announces them correctly; declaring a menu role would
        // require focus management (tabindex, arrow-key nav) we don't need
        // for two items.
        <div className="absolute right-0 top-full mt-1 w-44 z-30 bg-popover border border-border rounded-lg shadow-lg overflow-hidden">
          <a
            href={downloadJobLogUrl(jobId)}
            download={`${jobId}.log`}
            onClick={(e) => {
              e.stopPropagation()
              setOpen(false)
            }}
            className="flex items-center gap-2 px-3 py-2 text-xs text-foreground hover:bg-secondary/60 transition-colors"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Download log
          </a>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setOpen(false)
              onDelete(jobId)
            }}
            className="flex items-center gap-2 px-3 py-2 text-xs text-destructive hover:bg-destructive/10 transition-colors w-full text-left"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Delete entry
          </button>
        </div>
      )}
    </div>
  )
}
