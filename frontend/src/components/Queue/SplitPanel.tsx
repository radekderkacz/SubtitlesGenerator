import type { ReactNode } from 'react'

type Props = Readonly<{
  list: ReactNode
  detail: ReactNode
}>

export default function SplitPanel({ list, detail }: Props) {
  return (
    <div className="flex h-full">
      <section
        aria-label="Job queue"
        className="w-[340px] shrink-0 border-r border-border flex flex-col bg-background"
      >
        {list}
      </section>
      <aside
        aria-label="Job detail"
        className="flex-1 hidden xl:flex bg-background overflow-y-auto"
      >
        {detail}
      </aside>
    </div>
  )
}
