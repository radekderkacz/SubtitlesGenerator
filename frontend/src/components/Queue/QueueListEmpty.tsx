import { Link } from 'react-router'
import { FolderOpen } from 'lucide-react'

export default function QueueListEmpty() {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-16 gap-4">
      <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">
        <FolderOpen className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      </div>
      <p className="text-sm text-muted-foreground max-w-[260px]">
        No jobs yet. Browse your library to generate subtitles for a film.
      </p>
      <Link
        to="/browse"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
      >
        Browse Library
      </Link>
    </div>
  )
}
