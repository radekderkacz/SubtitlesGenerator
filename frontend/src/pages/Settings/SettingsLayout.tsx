import { useState, useCallback } from 'react'
import type { ReactNode } from 'react'
import SettingsRail from './SettingsRail'
import type { SectionId } from './sections'
import NasPathsPane from './NasPathsPane'
import JellyfinPane from './JellyfinPane'
import AiBackendsPane from './AiBackendsPane'
import SavedConfigurationsPane from './SavedConfigurationsPane'

const PANES: Record<SectionId, (p: { onDirtyChange: (d: boolean) => void }) => ReactNode> = {
  media: (p) => <NasPathsPane {...p} />,
  jellyfin: (p) => <JellyfinPane {...p} />,
  'ai-backends': (p) => <AiBackendsPane {...p} />,
  'saved-configurations': () => <SavedConfigurationsPane />,
}

export default function SettingsLayout({ section }: Readonly<{ section: SectionId }>) {
  const [dirty, setDirty] = useState<Partial<Record<SectionId, boolean>>>({})
  const anyDirty = Object.values(dirty).some(Boolean)
  const onDirtyChange = useCallback(
    (d: boolean) => setDirty((prev) => ({ ...prev, [section]: d })),
    [section],
  )

  return (
    <div className="max-w-[1280px] mx-auto p-6">
      <h1 className="text-2xl font-semibold tracking-tight text-foreground mb-1">Settings</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Configure storage, integrations and AI backends.
      </p>
      <div className="flex gap-6 items-start">
        <SettingsRail active={section} />
        <section className="flex-1 min-w-0 bg-card rounded-xl p-6 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] border border-white/[0.05]">
          {PANES[section]({ onDirtyChange })}
        </section>
      </div>
      {anyDirty && (
        <section
          aria-label="Unsaved changes"
          className="fixed bottom-0 left-64 right-0 bg-popover border-t border-border px-6 py-4 flex items-center justify-end gap-4 z-30"
        >
          <span className="text-sm text-muted-foreground mr-auto">You have unsaved changes.</span>
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={() => setDirty((p) => ({ ...p, [section]: false }))}
          >
            Discard
          </button>
          <button
            type="button"
            className="bg-[var(--action-accent)] text-white rounded-lg px-6 py-2 text-xs font-semibold uppercase tracking-wider shadow-[0_0_15px_rgba(59,130,246,0.3)]"
            onClick={() => globalThis.dispatchEvent(new CustomEvent('settings:save', { detail: section }))}
          >
            Save changes
          </button>
        </section>
      )}
    </div>
  )
}
