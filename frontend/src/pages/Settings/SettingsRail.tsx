import { Link } from 'react-router'
import { SECTIONS, type SectionId, type SectionGroup } from './sections'
import StatusDot from '@/components/Settings/StatusDot'
import { useSettingsStatusStore } from '@/store/settingsStatusStore'

const GROUP_ORDER: SectionGroup[] = ['STORAGE', 'INTEGRATIONS', 'AI']

export default function SettingsRail({ active }: Readonly<{ active: SectionId }>) {
  const byId = useSettingsStatusStore((s) => s.byId)
  return (
    <nav
      aria-label="Settings sections"
      className="w-64 shrink-0 bg-popover rounded-xl p-4 h-fit flex flex-col gap-6 sticky top-6"
    >
      {GROUP_ORDER.map((group) => (
        <div key={group}>
          <p className="text-[10px] text-muted-foreground font-bold tracking-[0.2em] px-2 mb-2 block">
            {group}
          </p>
          <ul className="space-y-1">
            {SECTIONS.filter((s) => s.group === group).map((s) => {
              const isActive = s.id === active
              return (
                <li key={s.id}>
                  <Link
                    to={`/settings/${s.id}`}
                    aria-current={isActive ? 'page' : undefined}
                    className={
                      isActive
                        ? 'flex items-center gap-2 px-2 py-1 rounded-l-lg text-primary font-bold bg-primary/10 border-r-2 border-primary'
                        : 'flex items-center gap-2 px-2 py-1 rounded-lg text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                    }
                  >
                    <StatusDot status={(byId[s.id] ?? { status: 'idle' as const }).status} />
                    <span>{s.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}
