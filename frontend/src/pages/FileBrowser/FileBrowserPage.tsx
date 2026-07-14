import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Filter, LayoutGrid, RefreshCw } from 'lucide-react'
import DirectoryTree from '@/components/FileBrowser/DirectoryTree'
import FileList from '@/components/FileBrowser/FileList'
import BatchActionBar from '@/components/FileBrowser/BatchActionBar'
import BatchPanel from '@/components/FileBrowser/BatchPanel'
import BatchSelectionStrip from '@/components/FileBrowser/BatchSelectionStrip'
import SubmitSheet from '@/components/SubmitSheet/SubmitSheet'
import GenerationPanel from '@/components/SubmitSheet/GenerationPanel'
import type { FileBrowseEntry } from '@/types/api'
import { browseDirectory } from '@/lib/api'

// Tailwind's `xl` breakpoint — kept in JS so the panel-vs-sheet branch and
// CSS `xl:` utilities stay in lockstep.
const XL_BREAKPOINT_PX = 1280

type Props = Readonly<Record<string, never>>

export default function FileBrowserPage(_props: Props) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [submitFile, setSubmitFile] = useState<FileBrowseEntry | null>(null)
  const [submitFullPath, setSubmitFullPath] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  // Batch submission: full paths the user has checkbox-selected.
  const [batchSelected, setBatchSelected] = useState<ReadonlySet<string>>(new Set())
  const queryClient = useQueryClient()

  // Re-fetch the current directory's listing so the BatchActionBar can map
  // each selected fullPath back to its FileBrowseEntry (for the
  // has_srt-based "skip files with SRT" filter).
  const browseQuery = useQuery({
    queryKey: ['browse', selectedPath],
    queryFn: () => browseDirectory(selectedPath ?? undefined),
    enabled: selectedPath !== null,
    retry: false,
  })
  const fileIndex = useMemo(() => {
    const m = new Map<string, FileBrowseEntry>()
    const dir = browseQuery.data?.path ?? ''
    for (const f of browseQuery.data?.files ?? []) {
      const fp = dir.endsWith('/') ? `${dir}${f.name}` : `${dir}/${f.name}`
      m.set(fp, f)
    }
    return m
  }, [browseQuery.data])

  const toggleBatchSelected = (fullPath: string) => {
    setBatchSelected((prev) => {
      const next = new Set(prev)
      if (next.has(fullPath)) next.delete(fullPath)
      else next.add(fullPath)
      return next
    })
  }

  const handleFileClick = (file: FileBrowseEntry, fullPath: string) => {
    setSubmitFile(file)
    setSubmitFullPath(fullPath)
    // On wide viewports the GenerationPanel right-rail is always visible
    // and updates live as the user picks files; only fall back to the
    // SubmitSheet popup on narrower screens where the rail is hidden.
    const wide = globalThis.window !== undefined && globalThis.window.innerWidth >= XL_BREAKPOINT_PX
    if (!wide) setSheetOpen(true)
  }

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['browse'] }).catch(() => {})
  }

  const folderName = selectedPath?.split('/').pop() ?? selectedPath ?? null

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      {/* LOCATIONS pane */}
      <aside
        aria-label="Locations"
        className="w-64 shrink-0 border-r border-border bg-popover overflow-y-auto min-h-0"
      >
        <header className="p-4 sticky top-0 bg-popover/90 backdrop-blur z-10 flex items-center justify-between">
          <h1 className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">
            Locations
          </h1>
          <button
            type="button"
            onClick={handleRefresh}
            aria-label="Refresh file system"
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </header>
        <div className="px-2 pb-3">
          <DirectoryTree selectedPath={selectedPath} onSelect={setSelectedPath} />
        </div>
      </aside>

      {/* File list pane */}
      <section className="flex-1 flex flex-col bg-background overflow-hidden min-h-0">
        {selectedPath === null ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            Select a folder from Locations to see its files.
          </div>
        ) : (
          <>
            <header className="px-6 py-5 border-b border-border flex items-center justify-between bg-background/90 backdrop-blur z-10">
              <div>
                <h2 className="text-lg font-semibold text-foreground">{folderName}</h2>
                <p className="text-xs text-muted-foreground mt-1 font-mono">{selectedPath}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled
                  title="Filter (coming soon)"
                  className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary/30 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  aria-label="Filter files"
                >
                  <Filter className="h-4 w-4" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  disabled
                  title="Grid view (coming soon)"
                  className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary/30 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  aria-label="Grid view"
                >
                  <LayoutGrid className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </header>
            <div className="flex-1 overflow-y-auto p-4 pb-24">
              <FileList
                path={selectedPath}
                onFileClick={handleFileClick}
                selectedPaths={batchSelected}
                onToggleSelected={toggleBatchSelected}
              />
            </div>
          </>
        )}
      </section>

      {batchSelected.size > 0 ? (
        <BatchPanel
          selectedPaths={[...batchSelected]}
          fileIndex={fileIndex}
          onCleared={() => setBatchSelected(new Set())}
        />
      ) : (
        <GenerationPanel file={submitFile} fullPath={submitFullPath} />
      )}

      <SubmitSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        file={submitFile}
        fullPath={submitFullPath}
      />

      {batchSelected.size > 0 && (
        <>
          <BatchSelectionStrip count={batchSelected.size} onClear={() => setBatchSelected(new Set())} />
          <BatchActionBar
            selectedPaths={[...batchSelected]}
            fileIndex={fileIndex}
            onCleared={() => setBatchSelected(new Set())}
          />
        </>
      )}
    </div>
  )
}
