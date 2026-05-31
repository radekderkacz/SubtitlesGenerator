type Props = Readonly<{
  count?: number
}>

const SKELETON_KEYS = ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'] as const

export default function QueueListSkeleton({ count = 3 }: Props) {
  const keys = SKELETON_KEYS.slice(0, Math.min(count, SKELETON_KEYS.length))
  return (
    <output aria-label="Loading jobs" className="block">
      {keys.map((key) => (
        <div
          key={key}
          className="border-b border-secondary/50 p-4 animate-pulse"
          aria-hidden="true"
        >
          <div className="flex justify-between items-start mb-1">
            <div className="h-4 w-3/5 rounded bg-secondary/70" />
            <div className="h-4 w-4 rounded bg-secondary/70" />
          </div>
          <div className="h-2.5 w-2/5 rounded bg-secondary/40 mb-3" />
          <div className="flex items-center justify-between mb-2">
            <div className="h-4 w-20 rounded-full bg-secondary/70" />
            <div className="h-3 w-12 rounded bg-secondary/40" />
          </div>
          <div className="w-full h-1 rounded-full bg-secondary/40" />
        </div>
      ))}
    </output>
  )
}
