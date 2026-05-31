import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Folder, Loader2 } from 'lucide-react'
import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ApiRequestError, browseDirectory } from '@/lib/api'

type Props = Readonly<{
  selectedPath: string | null
  onSelect: (path: string) => void
}>

const NOT_CONFIGURED_CODE = 'NAS_NOT_CONFIGURED'

export default function DirectoryTree({ selectedPath, onSelect }: Props) {
  const rootQuery = useQuery({
    queryKey: ['browse', null],
    queryFn: () => browseDirectory(),
    retry: false,
  })

  if (rootQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading directory tree…
      </div>
    )
  }

  if (rootQuery.isError) {
    const err = rootQuery.error
    if (err instanceof ApiRequestError && err.code === NOT_CONFIGURED_CODE) {
      return <NotConfiguredEmptyState />
    }
    const message = err instanceof Error ? err.message : 'Failed to load directory tree'
    return <ErrorState message={message} />
  }

  const root = rootQuery.data
  if (!root) return null

  return (
    <nav aria-label="Directory tree" className="font-mono text-sm space-y-1">
      <div className="flex items-center gap-2 py-1 px-2 text-foreground">
        <ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
        <Folder
          className="h-4 w-4 text-amber-500"
          fill="currentColor"
          aria-hidden="true"
        />
        <span className="text-xs truncate" title={root.path}>{root.path}</span>
      </div>
      {root.directories.length === 0 ? (
        <p className="pl-6 text-xs text-muted-foreground py-1 italic">
          No subdirectories
        </p>
      ) : (
        <ul className="pl-6 space-y-0.5 list-none">
          {root.directories.map((name) => (
            <DirectoryNode
              key={name}
              path={joinPath(root.path, name)}
              name={name}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </nav>
  )
}

type NodeProps = Readonly<{
  path: string
  name: string
  selectedPath: string | null
  onSelect: (path: string) => void
}>

function chevronIcon(expanded: boolean, isLoading: boolean): ReactNode {
  if (isLoading) return <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
  if (expanded) return <ChevronDown className="h-3 w-3" aria-hidden="true" />
  return <ChevronRight className="h-3 w-3" aria-hidden="true" />
}

function DirectoryNode({ path, name, selectedPath, onSelect }: NodeProps) {
  const [expanded, setExpanded] = useState(false)
  const childrenQuery = useQuery({
    queryKey: ['browse', path],
    queryFn: () => browseDirectory(path),
    enabled: expanded,
    retry: false,
  })

  const isSelected = selectedPath === path
  const isLoading = expanded && childrenQuery.isFetching && !childrenQuery.data

  const toggle = () => setExpanded((v) => !v)
  const handleSelect = () => onSelect(path)

  return (
    <li aria-current={isSelected ? 'true' : undefined}>
      <div
        className={`flex items-center gap-1 py-1.5 px-2 rounded transition-colors ${
          isSelected
            ? 'bg-primary/10 text-primary border-l-2 border-primary'
            : 'text-muted-foreground hover:bg-card hover:text-foreground'
        }`}
      >
        <button
          type="button"
          aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
          aria-expanded={expanded}
          onClick={toggle}
          className="shrink-0 rounded hover:bg-secondary p-0.5"
        >
          {chevronIcon(expanded, isLoading)}
        </button>
        <button
          type="button"
          onClick={handleSelect}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              toggle()
            }
          }}
          className="flex items-center gap-2 flex-1 text-left min-w-0"
        >
          <Folder
            className={`h-4 w-4 shrink-0 ${isSelected ? 'text-primary' : ''}`}
            fill={isSelected ? 'currentColor' : 'none'}
            aria-hidden="true"
          />
          <span className="truncate" title={path}>
            {name}
          </span>
        </button>
      </div>
      {expanded && (
        <ChildList
          query={childrenQuery}
          parentPath={path}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      )}
    </li>
  )
}

type ChildListProps = Readonly<{
  query: ReturnType<typeof useQuery<import('@/types/api').FileBrowseResponse>>
  parentPath: string
  selectedPath: string | null
  onSelect: (path: string) => void
}>

function ChildList({ query, parentPath, selectedPath, onSelect }: ChildListProps) {
  if (query.isError) {
    return (
      <p className="pl-5 mt-0.5 text-xs text-destructive py-1 px-2">Failed to load</p>
    )
  }
  if (!query.data) return null
  if (query.data.directories.length === 0) {
    return (
      <p className="pl-5 mt-0.5 text-xs text-muted-foreground py-1 px-2 italic">
        Empty
      </p>
    )
  }
  return (
    <ul className="pl-5 mt-0.5 space-y-0.5 list-none">
      {query.data.directories.map((child) => (
        <DirectoryNode
          key={child}
          path={joinPath(parentPath, child)}
          name={child}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}

function NotConfiguredEmptyState() {
  return (
    <div className="px-3 py-6 text-sm space-y-3">
      <p className="text-muted-foreground">
        No media root configured. Go to Settings → NAS Paths to set one.
      </p>
      <Link
        to="/settings"
        className="inline-flex items-center px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
      >
        Open Settings
      </Link>
    </div>
  )
}

type ErrorStateProps = Readonly<{ message: string }>

function ErrorState({ message }: ErrorStateProps) {
  return (
    <div className="px-3 py-4 text-sm text-destructive">
      <p>Failed to load directory tree.</p>
      <p className="text-xs text-muted-foreground mt-1">{message}</p>
    </div>
  )
}

function joinPath(parent: string, name: string): string {
  if (parent.endsWith('/')) return `${parent}${name}`
  return `${parent}/${name}`
}
