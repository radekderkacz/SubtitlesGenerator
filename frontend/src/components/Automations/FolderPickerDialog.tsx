import { useState, useEffect } from 'react'
import { Folder, FolderOpen, ChevronRight, Loader2 } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { browseDirectory } from '@/lib/api'
import type { FileBrowseResponse } from '@/types/api'

type Props = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  currentPath?: string
  onSelect: (path: string) => void
}>

export default function FolderPickerDialog({ open, onOpenChange, currentPath, onSelect }: Props) {
  const [browsePath, setBrowsePath] = useState<string | undefined>(currentPath)
  const [browseData, setBrowseData] = useState<FileBrowseResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async (path?: string) => {
    setLoading(true)
    setError(null)
    try {
      let data
      try {
        data = await browseDirectory(path)
      } catch (error_) {
        // Browse is an explore affordance — a starting path that is empty,
        // relative, stale, or outside the NAS mount root must NOT dead-end
        // the dialog (the backend rejects those with "Path is outside NAS
        // mount root"). Fall back to the NAS root so Browse always opens.
        if (path === undefined) throw error_
        data = await browseDirectory()
      }
      setBrowseData(data)
      setBrowsePath(data.path)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load directory')
    } finally {
      setLoading(false)
    }
  }

  // Load when dialog opens (both via prop and via dialog's own open event)
  useEffect(() => {
    if (open && !browseData && !loading) {
      void load(currentPath)
    }
    // Reset when closed so next open re-loads
    if (!open) {
      setBrowseData(null)
      setBrowsePath(currentPath)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenChange = (o: boolean) => {
    onOpenChange(o)
  }

  const navigate = (dir: string) => {
    const newPath = browsePath ? `${browsePath.replace(/\/$/, '')}/${dir}` : `/${dir}`
    void load(newPath)
  }

  const navigateUp = () => {
    if (browseData?.parent) {
      void load(browseData.parent)
    }
  }

  const handleSelect = () => {
    if (browsePath) {
      onSelect(browsePath)
      onOpenChange(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-[#10131a] border-[#424754] text-[#e1e2ec] max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-[#e1e2ec]">Browse NAS Folder</DialogTitle>
        </DialogHeader>

        {/* Current path */}
        <div className="flex items-center gap-2 px-3 py-2 bg-zinc-900 rounded-lg border border-zinc-700 text-sm font-mono text-[#e1e2ec]">
          <FolderOpen className="h-4 w-4 text-amber-500 shrink-0" aria-hidden="true" />
          <span className="truncate">{browsePath ?? '/'}</span>
        </div>

        {/* Navigate up */}
        {browseData?.parent && (
          <button
            onClick={navigateUp}
            className="flex items-center gap-2 px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors text-left"
          >
            <span>↑ ..</span>
          </button>
        )}

        {/* Directory list */}
        <div className="max-h-64 overflow-y-auto space-y-0.5">
          {loading && (
            <div className="flex items-center gap-2 px-3 py-4 text-sm text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading…
            </div>
          )}
          {error && (
            <p className="px-3 py-2 text-sm text-red-400">{error}</p>
          )}
          {!loading && browseData?.directories.length === 0 && (
            <p className="px-3 py-2 text-sm text-zinc-500 italic">No subdirectories</p>
          )}
          {!loading && browseData?.directories.map((dir) => (
            <button
              key={dir}
              onClick={() => navigate(dir)}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[#e1e2ec] hover:bg-zinc-800 rounded-lg transition-colors text-left"
            >
              <Folder className="h-4 w-4 text-amber-500 shrink-0" aria-hidden="true" />
              <span className="flex-1 font-mono truncate">{dir}</span>
              <ChevronRight className="h-3 w-3 text-zinc-600 shrink-0" aria-hidden="true" />
            </button>
          ))}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            className="text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSelect}
            disabled={!browsePath}
            className="bg-[var(--action-accent)] text-white shadow-[0_0_15px_rgba(59,130,246,0.3)] hover:bg-blue-400"
          >
            Select this folder
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
