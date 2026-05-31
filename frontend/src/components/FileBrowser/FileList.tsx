import { useQuery } from '@tanstack/react-query'
import { ApiRequestError, browseDirectory } from '@/lib/api'
import { formatBytes } from '@/lib/utils'
import type { FileBrowseEntry } from '@/types/api'
import SrtBadge from './SrtBadge'

type Props = Readonly<{
  path: string
  onFileClick: (file: FileBrowseEntry, fullPath: string) => void
  /** Currently-selected paths for batch submission. */
  selectedPaths?: ReadonlySet<string>
  /** Called when the checkbox on a row is toggled. */
  onToggleSelected?: (fullPath: string) => void
}>

const SKELETON_KEYS = ['k0', 'k1', 'k2', 'k3', 'k4'] as const

function formatModified(iso: string): string {
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return iso
  return new Date(ms).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function joinPath(parent: string, name: string): string {
  if (parent.endsWith('/')) return `${parent}${name}`
  return `${parent}/${name}`
}

export default function FileList({ path, onFileClick, selectedPaths, onToggleSelected }: Props) {
  const query = useQuery({
    queryKey: ['browse', path],
    queryFn: () => browseDirectory(path),
    retry: false,
  })

  if (query.isLoading) {
    return <FileListSkeleton />
  }

  if (query.isError) {
    const err = query.error
    const message = err instanceof ApiRequestError ? err.message : 'Failed to load files'
    return (
      <div role="alert" className="text-sm text-destructive py-8 text-center">
        {message}
      </div>
    )
  }

  const data = query.data
  if (!data) return null

  if (data.files.length === 0) {
    return (
      <output className="block text-sm text-muted-foreground py-12 text-center italic">
        No video files in this directory.
      </output>
    )
  }

  const batchEnabled = onToggleSelected !== undefined

  return (
    <table className="w-full text-left border-collapse">
      <thead>
        <tr className="border-b border-border">
          {batchEnabled && <th className="pb-3 w-10"><span className="sr-only">Select</span></th>}
          <th className="pb-3 text-xs uppercase font-medium text-muted-foreground tracking-wider">
            Filename
          </th>
          <th className="pb-3 text-xs uppercase font-medium text-muted-foreground tracking-wider w-24">
            Size
          </th>
          <th className="pb-3 text-xs uppercase font-medium text-muted-foreground tracking-wider w-32">
            Modified
          </th>
          <th className="pb-3 text-xs uppercase font-medium text-muted-foreground tracking-wider w-24">
            SRT
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border/30">
        {data.files.map((file) => {
          const fullPath = joinPath(path, file.name)
          return (
            <FileRow
              key={file.name}
              file={file}
              fullPath={fullPath}
              onClick={onFileClick}
              isSelected={selectedPaths?.has(fullPath) ?? false}
              onToggleSelected={onToggleSelected}
            />
          )
        })}
      </tbody>
    </table>
  )
}

type FileRowProps = Readonly<{
  file: FileBrowseEntry
  fullPath: string
  onClick: (file: FileBrowseEntry, fullPath: string) => void
  isSelected: boolean
  onToggleSelected?: (fullPath: string) => void
}>

function FileRow({ file, fullPath, onClick, isSelected, onToggleSelected }: FileRowProps) {
  const batchEnabled = onToggleSelected !== undefined
  return (
    <tr
      onClick={() => onClick(file, fullPath)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(file, fullPath)
        }
      }}
      tabIndex={0}
      className="cursor-pointer hover:bg-card/50 transition-colors h-10 focus:outline-none focus:ring-2 focus:ring-primary/50"
    >
      {batchEnabled && (
        <td className="py-3 w-10" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelected?.(fullPath)}
            aria-label={`Select ${file.name} for batch submission`}
            className="h-4 w-4 cursor-pointer accent-primary"
          />
        </td>
      )}
      <td className="py-3 font-mono text-xs text-foreground truncate" title={file.name}>
        {file.name}
      </td>
      <td className="py-3 text-xs text-muted-foreground">{formatBytes(file.size_bytes)}</td>
      <td className="py-3 text-xs text-muted-foreground">{formatModified(file.modified_at)}</td>
      <td className="py-3">
        <SrtBadge hasSrt={file.has_srt} />
      </td>
    </tr>
  )
}

function FileListSkeleton() {
  return (
    <output aria-label="Loading files" className="block">
      <table className="w-full">
        <tbody>
          {SKELETON_KEYS.map((key) => (
            <tr key={key} className="border-b border-border/50 h-10 animate-pulse">
              <td className="py-3">
                <div className="h-4 w-3/4 rounded bg-secondary/70" />
              </td>
              <td className="py-3">
                <div className="h-4 w-16 rounded bg-secondary/40" />
              </td>
              <td className="py-3">
                <div className="h-4 w-24 rounded bg-secondary/40" />
              </td>
              <td className="py-3">
                <div className="h-4 w-16 rounded-full bg-secondary/40" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </output>
  )
}
