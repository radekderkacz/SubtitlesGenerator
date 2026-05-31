import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { createTrigger, updateTrigger, fireTrigger } from '@/lib/api'
import type { Trigger, TriggerType, Action, FileFilter, Schedule } from '@/types/api'
import ActionPicker from './ActionPicker'
import FileFilterField from './FileFilterField'
import PathField from './PathField'
import ScheduleBuilder from './ScheduleBuilder'
import WebhookSnippet from './WebhookSnippet'

type Props = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  trigger?: Trigger
}>

const DEFAULT_ACTION: Action = {
  profile_name: '',
  source_language: null,
  target_language: null,
  skip_if_srt: true,
}

const DEFAULT_FILE_FILTER: FileFilter = { type: 'all', value: null }

const DEFAULT_SCHEDULE: Schedule = { mode: 'daily', time: '03:00' }

export default function TriggerEditorSheet({ open, onOpenChange, trigger }: Props) {
  const isEdit = trigger != null
  const qc = useQueryClient()

  const [name, setName] = useState(trigger?.name ?? '')
  const [type, setType] = useState<TriggerType>(trigger?.type ?? 'watch')

  // Watch path
  const [path, setPath] = useState<string>(
    typeof trigger?.config?.path === 'string' ? trigger.config.path : '',
  )

  // Cron scan path + schedule
  const [scanPath, setScanPath] = useState<string>(
    typeof trigger?.config?.scan_path === 'string' ? trigger.config.scan_path : '',
  )
  const [schedule, setSchedule] = useState<Schedule>(
    (trigger?.config?.schedule as Schedule) ?? DEFAULT_SCHEDULE,
  )

  // Action
  const [action, setAction] = useState<Action>(trigger?.action ?? DEFAULT_ACTION)

  // File filter
  const [fileFilter, setFileFilter] = useState<FileFilter>(
    trigger?.file_filter ?? DEFAULT_FILE_FILTER,
  )

  // Default off so creation never silently submits many jobs.
  const [scanExisting, setScanExisting] = useState(false)

  const buildConfig = (): Record<string, unknown> => {
    if (type === 'watch') return { path }
    if (type === 'cron') return { scan_path: scanPath, schedule }
    return {}
  }

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name,
        type,
        config: buildConfig(),
        action,
        file_filter: fileFilter,
        enabled: true,
      }
      if (isEdit && trigger) {
        return updateTrigger(trigger.id, {
          name,
          config: buildConfig(),
          action,
          file_filter: fileFilter,
          enabled: true,
        })
      }
      return createTrigger(body)
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['triggers'] })
      onOpenChange(false)
      // Fire-and-forget the initial scan so the sheet closes immediately.
      // The walk can enqueue many jobs on a large folder; awaiting would
      // freeze the editor on "Saving…" for the whole walk. The user has
      // "Run now" on the card if this fails.
      if (!isEdit && type === 'watch' && scanExisting && created?.id) {
        fireTrigger(created.id).catch((err) => {
          console.warn('initial scan failed', err)
        })
      }
    },
  })

  const handleSave = () => {
    mutation.mutate()
  }

  const scopePath = type === 'watch' ? path : scanPath

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[600px] sm:max-w-[600px] overflow-y-auto bg-[#10131a] border-[#424754]"
      >
        <SheetHeader className="mb-6">
          <SheetTitle className="text-[#e1e2ec]">
            {isEdit ? 'Edit Trigger' : 'New Trigger'}
          </SheetTitle>
        </SheetHeader>

        <div className="space-y-6 pb-24">
          {/* Name */}
          <div className="space-y-2">
            <Label
              htmlFor="trigger-name"
              className="text-xs font-semibold text-zinc-400 uppercase tracking-wider"
            >
              Name
            </Label>
            <Input
              id="trigger-name"
              aria-label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My trigger"
              className="h-12 bg-zinc-900 border-zinc-700 text-[#e1e2ec] rounded-lg"
            />
          </div>

          {/* Type selector — locked after create */}
          {!isEdit && (
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Trigger Type
              </Label>
              <div className="flex gap-2">
                {(['watch', 'cron', 'webhook'] as TriggerType[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-label={t}
                    onClick={() => setType(t)}
                    className={`flex-1 py-2 text-xs font-semibold rounded-lg border transition-colors capitalize ${
                      type === t
                        ? 'bg-primary/10 text-primary border-primary'
                        : 'border-zinc-700 text-zinc-400 hover:text-[#e1e2ec]'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Watch path */}
          {type === 'watch' && (
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Watch Path
              </Label>
              <PathField
                value={path}
                onChange={setPath}
                placeholder="/shared/TV"
              />
              {!isEdit && (
                <label className="flex items-start gap-3 mt-3 px-3 py-2.5 bg-blue-500/5 border border-blue-500/10 rounded-lg cursor-pointer hover:bg-blue-500/10 transition-colors">
                  <input
                    type="checkbox"
                    checked={scanExisting}
                    onChange={(e) => setScanExisting(e.target.checked)}
                    aria-label="Scan existing files in this folder when saving"
                    className="mt-0.5 h-4 w-4 rounded border-zinc-600 bg-zinc-900 text-blue-500 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
                  />
                  <div className="text-xs text-zinc-300">
                    <div className="font-medium">Scan existing files in this folder when saving</div>
                    <p className="text-zinc-500 mt-0.5">
                      Without this, the trigger only fires on new file arrivals — existing movies without SRTs stay untouched until somebody re-saves them.
                    </p>
                  </div>
                </label>
              )}
            </div>
          )}

          {/* Cron: scan path + schedule */}
          {type === 'cron' && (
            <>
              <div className="space-y-2">
                <Label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                  Scan Path
                </Label>
                <PathField
                  value={scanPath}
                  onChange={setScanPath}
                  placeholder="/shared"
                />
              </div>
              <ScheduleBuilder value={schedule} onChange={setSchedule} />
            </>
          )}

          {/* Webhook info */}
          {type === 'webhook' && (
            <>
              <p className="text-xs text-zinc-400 bg-blue-500/5 border border-blue-500/10 px-4 py-3 rounded-lg">
                After saving, a webhook secret will be generated. Use it to send POST requests to{' '}
                <code className="font-mono">/api/v1/triggers/&lt;id&gt;/webhook</code>.
              </p>
              {isEdit && trigger && (
                <WebhookSnippet triggerId={trigger.id} secret={null} />
              )}
            </>
          )}

          {/* File Filter */}
          <div className="space-y-2">
            <Label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
              File Filter
            </Label>
            <FileFilterField
              value={fileFilter}
              onChange={setFileFilter}
              scopePath={scopePath}
            />
          </div>

          {/* Action */}
          <div className="space-y-2">
            <Label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
              Action
            </Label>
            <ActionPicker value={action} onChange={setAction} />
          </div>
        </div>

        {/* Sticky footer */}
        <SheetFooter className="absolute bottom-0 left-0 right-0 bg-[#10131a]/80 backdrop-blur-xl border-t border-white/5 px-6 py-4 flex gap-3 justify-end">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
            className="text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={mutation.isPending || !name.trim()}
            className="bg-[var(--action-accent)] text-white shadow-[0_0_15px_rgba(59,130,246,0.3)]"
            aria-label="Save"
          >
            {mutation.isPending ? 'Saving…' : 'Save trigger'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
