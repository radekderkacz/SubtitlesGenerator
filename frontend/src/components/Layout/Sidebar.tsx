import { NavLink } from 'react-router'
import {
  History,
  Inbox,
  Plus,
  Settings,
  Sparkles,
  Video,
} from 'lucide-react'
import { useConnectionStatus, type ConnectionStatus } from '@/hooks/useConnectionStatus'

type Props = Readonly<Record<string, never>>

const NAV_ITEMS = [
  { to: '/', label: 'Queue', icon: Inbox, exact: true },
  { to: '/browse', label: 'Library', icon: Video, exact: false },
  { to: '/automations', label: 'Automations', icon: Sparkles, exact: false },
  { to: '/history', label: 'History', icon: History, exact: false },
  { to: '/settings', label: 'Settings', icon: Settings, exact: false },
] as const

export default function Sidebar(_props: Props) {
  return (
    <aside className="bg-sidebar fixed left-0 top-0 h-screen w-64 flex flex-col py-8 px-4 z-20">
      {/* Brand block — product is "SubtitlesGen" (org: "by Derkos Labs").
          The product name and org are rendered below. */}
      <div className="px-2 mb-8">
        <h1 className="text-lg font-bold text-primary leading-tight tracking-tight">
          SubtitlesGen
        </h1>
        <p className="text-xs text-muted-foreground mt-1">by Derkos Labs</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 flex flex-col gap-1" aria-label="Main navigation">
        {NAV_ITEMS.map(({ to, label, icon: Icon, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              isActive
                ? 'flex items-center gap-3 px-3 py-2 rounded-lg text-primary bg-primary/10 border-r-2 border-primary font-medium transition-colors'
                : 'flex items-center gap-3 px-3 py-2 rounded-lg text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition-colors'
            }
          >
            <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
            <span className="text-xs font-semibold tracking-wider uppercase">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer — connection status + New Task CTA */}
      <div className="mt-auto px-2 space-y-3">
        <SseStatusDot />
        <button
          type="button"
          className="w-full bg-[var(--action-accent)] hover:bg-[var(--action-accent)]/90 text-white rounded-lg py-2 px-3 text-xs font-semibold uppercase tracking-wider flex items-center justify-center gap-2 transition-colors active:scale-95"
          onClick={() => globalThis.location.assign('/browse')}
          aria-label="New task — go to file browser"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          New Task
        </button>
      </div>
    </aside>
  )
}

const STATUS_TO_DOT_CLASS: Record<ConnectionStatus, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
}

const STATUS_TO_LABEL: Record<ConnectionStatus, string> = {
  green: 'Online',
  amber: 'Reconnecting…',
  red: 'Offline',
}

function SseStatusDot() {
  const status = useConnectionStatus()
  const dotClass = STATUS_TO_DOT_CLASS[status]
  return (
    <div className="flex items-center gap-2">
      <span
        data-testid="sse-status-dot"
        data-status={status}
        className="relative flex h-2 w-2 shrink-0"
        aria-label={STATUS_TO_LABEL[status]}
      >
        {status === 'green' && (
          <span
            aria-hidden="true"
            className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dotClass} opacity-75`}
          />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${dotClass}`} />
      </span>
      <span className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">
        {STATUS_TO_LABEL[status]}
      </span>
    </div>
  )
}
