import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Sparkles } from 'lucide-react'
import { listTriggers, fireTrigger, revealTriggerSecret, deleteTrigger } from '@/lib/api'
import type { Trigger } from '@/types/api'
import TriggerCard from '@/components/Automations/TriggerCard'
import TriggerEditorSheet from '@/components/Automations/TriggerEditorSheet'
import ActivityFeed from '@/components/Automations/ActivityFeed'
import WebhookSnippet from '@/components/Automations/WebhookSnippet'

type Props = Readonly<Record<string, never>>

type TriggerWithSecret = Trigger & { _webhookSecret: string }

function renderTriggerGrid(
  isLoading: boolean,
  triggers: Trigger[],
  handlers: {
    onEdit: (t: Trigger) => void
    onDelete: (t: Trigger) => void
    onFire: (t: Trigger) => void
    onRevealSecret: (t: Trigger) => void
  },
) {
  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading triggers…</p>
  }
  if (triggers.length === 0) {
    return (
      <section className="bg-card border border-white/[0.05] rounded-xl p-12 text-center shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)]">
        <div className="w-14 h-14 mx-auto rounded-full bg-secondary/60 flex items-center justify-center text-muted-foreground mb-4">
          <Sparkles className="h-7 w-7" aria-hidden />
        </div>
        <h2 className="text-lg font-semibold text-foreground mb-1">No triggers yet</h2>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          Create a watch folder, scheduled scan, or webhook to automatically generate subtitles.
        </p>
      </section>
    )
  }
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
      {triggers.map((trigger) => (
        <TriggerCard
          key={trigger.id}
          trigger={trigger}
          onEdit={handlers.onEdit}
          onDelete={handlers.onDelete}
          onFire={handlers.onFire}
          onRevealSecret={handlers.onRevealSecret}
        />
      ))}
    </div>
  )
}

export default function AutomationsPage(_props: Props) {
  const qc = useQueryClient()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [editingTrigger, setEditingTrigger] = useState<Trigger | undefined>(undefined)
  const [snippetTrigger, setSnippetTrigger] = useState<TriggerWithSecret | undefined>(undefined)
  const dialogRef = useRef<HTMLDialogElement>(null)

  const { data: triggers = [], isLoading } = useQuery({
    queryKey: ['triggers'],
    queryFn: listTriggers,
  })

  const fireMutation = useMutation({
    mutationFn: (trigger: Trigger) => fireTrigger(trigger.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trigger_events'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (trigger: Trigger) => deleteTrigger(trigger.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['triggers'] })
    },
  })

  const handleNewTrigger = () => {
    setEditingTrigger(undefined)
    setSheetOpen(true)
  }

  const handleEdit = (trigger: Trigger) => {
    setEditingTrigger(trigger)
    setSheetOpen(true)
  }

  const handleDelete = (trigger: Trigger) => {
    deleteMutation.mutate(trigger)
  }

  const handleFire = (trigger: Trigger) => {
    fireMutation.mutate(trigger)
  }

  const handleRevealSecret = async (trigger: Trigger) => {
    const res = await revealTriggerSecret(trigger.id)
    if (res.webhook_secret) {
      setSnippetTrigger({ ...trigger, _webhookSecret: res.webhook_secret })
      dialogRef.current?.showModal()
    }
  }

  const handleCloseSnippet = () => {
    setSnippetTrigger(undefined)
    dialogRef.current?.close()
  }

  const gridHandlers = {
    onEdit: handleEdit,
    onDelete: handleDelete,
    onFire: handleFire,
    onRevealSecret: handleRevealSecret,
  }

  return (
    <div className="max-w-[1280px] mx-auto p-6 space-y-10">
      {/* Page header */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Automations</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Schedules, watch folders, and webhooks that submit subtitle jobs without manual clicking
          </p>
        </div>
        <button
          type="button"
          onClick={handleNewTrigger}
          className="bg-[var(--action-accent)] text-white px-5 py-2.5 rounded-lg font-bold uppercase tracking-wider shadow-[0_0_20px_rgba(59,130,246,0.3)] flex items-center gap-2 text-xs transition-all active:scale-95 shrink-0 hover:bg-blue-600"
          aria-label="New Trigger"
        >
          <Plus className="h-4 w-4" aria-hidden />
          NEW TRIGGER
        </button>
      </header>

      {/* Trigger grid */}
      {renderTriggerGrid(isLoading, triggers, gridHandlers)}

      {/* Recent Activity */}
      <section>
        <ActivityFeed />
      </section>

      {/* `key` forces remount per editing target — the editor seeds form
       * fields from props via useState defaults, which only run on mount.
       */}
      <TriggerEditorSheet
        key={editingTrigger?.id ?? 'new'}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        trigger={editingTrigger}
      />

      {/* Webhook snippet — native dialog element */}
      <dialog
        ref={dialogRef}
        aria-label="Webhook secret"
        className="fixed z-50 m-auto bg-card rounded-xl border border-white/[0.05] p-6 max-w-lg w-full mx-4 shadow-2xl backdrop:bg-black/60"
        onClose={handleCloseSnippet}
      >
        <h3 className="text-lg font-semibold text-foreground mb-4">Webhook Secret</h3>
        {snippetTrigger && (
          <WebhookSnippet
            triggerId={snippetTrigger.id}
            secret={snippetTrigger._webhookSecret}
          />
        )}
        <button
          type="button"
          className="mt-4 text-sm text-muted-foreground hover:text-foreground"
          onClick={handleCloseSnippet}
        >
          Close
        </button>
      </dialog>
    </div>
  )
}
