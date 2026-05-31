import { Outlet } from 'react-router'
import Sidebar from './Sidebar'
import BackgroundProcessingToast from './BackgroundProcessingToast'
import ConnectionBanner from '@/components/Queue/ConnectionBanner'
import { useJobStream } from '@/hooks/useJobStream'

type Props = Readonly<Record<string, never>>

export default function Layout(_props: Props) {
  // SSE lives in the shell so the connection (and lastEventAt) stays alive
  // across navigation. Previously the hook was on QueuePage only; navigating
  // away for >60s froze lastEventAt and the banner — also shell-level —
  // would falsely trigger on every other page.
  useJobStream()
  // SubtitlesGen redesign: no fixed top bar. Each page renders its own header
  // inside `main` so the page title and CTAs live in flow with the content
  // (matches the Active Queue / Library / Settings layouts).
  //
  // ConnectionBanner is mounted at app-shell level (not page-level) so a
  // stale SSE connection is surfaced on EVERY page — submitting from
  // Library while the queue is silently disconnected is the worst case,
  // and that page never used to show the banner. The banner self-hides
  // when isConnected && lastEventAt is fresh, so the cost on the happy
  // path is one render returning null.
  return (
    <div className="bg-background text-foreground min-h-screen">
      <Sidebar />
      <main className="ml-64 min-h-screen overflow-x-hidden">
        <ConnectionBanner />
        <Outlet />
      </main>
      <BackgroundProcessingToast />
    </div>
  )
}
