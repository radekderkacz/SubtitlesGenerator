import { useState } from 'react'
import { Link } from 'react-router'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import LanguageSelector from './LanguageSelector'
import { AUTO_DETECT } from '@/lib/iso639'
import type { JobSubmitPayload } from '@/lib/api'

export type GenerationControlsValues = Readonly<{
  sourceLanguage: string
  translate: boolean
  targetLanguage: string
  profileName: string
  /** null = untouched → omit from the payload and let the backend apply
   *  the global "prefer existing subtitles" setting. */
  useExistingSubs: boolean | null
}>

export const INITIAL_GENERATION_VALUES: GenerationControlsValues = {
  sourceLanguage: AUTO_DETECT.code,
  translate: false,
  targetLanguage: '',
  profileName: '',
  useExistingSubs: null,
}

/** Single source of truth for the submit-disable rule, mirroring the
 *  backend JobCreate validator. Returns a human reason or null. */
export function controlsBlockedReason(
  v: GenerationControlsValues,
  profilesCount: number,
): string | null {
  if (profilesCount === 0) return 'Create a profile in Settings first'
  if (!v.profileName) return 'Select a profile'
  if (v.translate && (!v.targetLanguage || v.targetLanguage === AUTO_DETECT.code))
    return 'Pick a target language'
  return null
}

/** Single source of truth for payload shaping (translate ⟹ concrete target). */
export function buildJobPayload(
  filePath: string,
  v: GenerationControlsValues,
): JobSubmitPayload {
  const payload: JobSubmitPayload = {
    file_path: filePath,
    profile_name: v.profileName,
    source_language: v.sourceLanguage,
    translate: v.translate,
  }
  if (v.translate && v.targetLanguage && v.targetLanguage !== AUTO_DETECT.code) {
    payload.target_language = v.targetLanguage
  }
  if (v.useExistingSubs !== null) {
    payload.use_existing_subs = v.useExistingSubs
  }
  return payload
}

/** Owns the 4 control fields + a reset to defaults (the reseed the
 *  single-file panels do on file/open change). */
export function useGenerationControlsState() {
  const [values, setValues] = useState<GenerationControlsValues>(INITIAL_GENERATION_VALUES)
  const onChange = (patch: Partial<GenerationControlsValues>) =>
    setValues((prev) => ({ ...prev, ...patch }))
  const reset = () => setValues(INITIAL_GENERATION_VALUES)
  return { values, onChange, reset }
}

type Props = Readonly<{
  idPrefix: string
  values: GenerationControlsValues
  profiles: ReadonlyArray<{ name: string }>
  onChange: (patch: Partial<GenerationControlsValues>) => void
  /** Global settings.prefer_existing_subs — what the switch shows until the
   *  user touches it. Defaults to true (the backend default). */
  existingSubsDefault?: boolean
  /** Called when the user clicks the "create one in Settings" link
   *  (SubmitSheet uses it to close its sheet). Optional. */
  onProfileLinkClick?: () => void
}>

export function GenerationControls({
  idPrefix, values, profiles, onChange, existingSubsDefault = true, onProfileLinkClick,
}: Props) {
  const blocked = controlsBlockedReason(values, profiles.length)
  const showTargetHint =
    values.translate && (!values.targetLanguage || values.targetLanguage === AUTO_DETECT.code)
  return (
    <div className="space-y-6">
      <LanguageSelector
        value={values.sourceLanguage}
        onChange={(c) => onChange({ sourceLanguage: c })}
        label="Source language (of the audio)"
        excludeAuto={false}
      />
      <div className="flex items-center justify-between py-2 border-t border-border pt-4">
        <Label htmlFor={`${idPrefix}-translate-toggle`} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Translate Subtitles
        </Label>
        <Switch
          id={`${idPrefix}-translate-toggle`}
          checked={values.translate}
          onCheckedChange={(checked) =>
            onChange(checked ? { translate: true } : { translate: false, targetLanguage: '' })}
        />
      </div>
      {values.translate && (
        <div className="space-y-2">
          <LanguageSelector
            value={values.targetLanguage}
            onChange={(c) => onChange({ targetLanguage: c })}
            label="Translate to"
            excludeAuto={true}
          />
          {showTargetHint && (
            <p className="text-[11px] text-amber-500 flex items-center gap-1.5">
              Pick a specific target language — Auto-detect is for source
              detection only.
            </p>
          )}
        </div>
      )}
      <div className="py-2 border-t border-border pt-4 space-y-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor={`${idPrefix}-existing-subs-toggle`} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Use Existing Subtitles
          </Label>
          <Switch
            id={`${idPrefix}-existing-subs-toggle`}
            checked={values.useExistingSubs ?? existingSubsDefault}
            onCheckedChange={(checked) => onChange({ useExistingSubs: checked })}
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          If the video ships with a subtitle track that passes verification,
          use it instead of transcribing — faster and usually more accurate.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-profile-trigger`} className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          AI Profile
        </Label>
        {profiles.length === 0 ? (
          <div className="p-4 rounded-lg bg-card border border-dashed border-border text-center space-y-1">
            <p className="text-xs text-muted-foreground italic">
              No profiles yet —{' '}
              <Link to="/settings" className="text-primary hover:underline" onClick={onProfileLinkClick}>
                create one in Settings → Profiles
              </Link>
            </p>
          </div>
        ) : (
          <Select value={values.profileName} onValueChange={(v) => onChange({ profileName: v ?? '' })}>
            <SelectTrigger id={`${idPrefix}-profile-trigger`} className="w-full">
              <SelectValue placeholder="Select a profile…" />
            </SelectTrigger>
            <SelectContent>
              {profiles.map((p) => (
                <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      {blocked && profiles.length > 0 && !showTargetHint && (
        <p className="sr-only" data-testid={`${idPrefix}-blocked-reason`}>{blocked}</p>
      )}
    </div>
  )
}

export default GenerationControls
