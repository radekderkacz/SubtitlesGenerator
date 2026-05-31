import { useId, useMemo, useState, type ChangeEvent } from 'react'
import { Check, Search } from 'lucide-react'
import { AUTO_DETECT, filterLanguages, findLanguage } from '@/lib/iso639'

type Props = Readonly<{
  value: string
  onChange: (code: string) => void
  autoFocus?: boolean
  label?: string
  /** When true, the "Auto-detect" pseudo-option is omitted. Use this when
   *  the language acts as a *translation target* — auto-detect only makes
   *  sense for source-language detection on Whisper, never as a target. */
  excludeAuto?: boolean
}>

/**
 * Language picker with a search input and a scrollable list. The first
 * option is always "Auto-detect" UNLESS ``excludeAuto`` is true; the rest
 * are filtered ISO 639-1 entries.
 *
 * Used by SubmitSheet + GenerationPanel. Uncontrolled-search / controlled-
 * value pattern: the parent owns the selected `code`; this component keeps
 * its own search query state.
 */
export default function LanguageSelector({
  value,
  onChange,
  autoFocus = false,
  label = 'Language',
  excludeAuto = false,
}: Props) {
  const [query, setQuery] = useState('')
  const inputId = useId()
  const filtered = useMemo(() => filterLanguages(query), [query])
  const selected = findLanguage(value)
  const showAuto =
    !excludeAuto &&
    (query.trim() === '' || AUTO_DETECT.english.toLowerCase().includes(query.toLowerCase()))

  const handleSearch = (e: ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)

  return (
    <div className="space-y-2">
      <label htmlFor={inputId} className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
        {label}
        {selected && (
          <span className="ml-2 text-foreground normal-case font-mono">{selected.english}</span>
        )}
      </label>
      <div className="relative">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          id={inputId}
          type="search"
          value={query}
          onChange={handleSearch}
          placeholder="Search…"
          autoFocus={autoFocus}
          className="w-full pl-9 pr-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>
      <ul
        className="max-h-56 overflow-y-auto rounded-md border border-border bg-background divide-y divide-border/30 list-none"
        aria-label="Language options"
      >
        {showAuto && (
          <LanguageRow
            option={AUTO_DETECT}
            selected={value === AUTO_DETECT.code}
            onSelect={() => onChange(AUTO_DETECT.code)}
          />
        )}
        {filtered.length === 0 && !showAuto && (
          <li className="px-3 py-2 text-xs text-muted-foreground italic">
            No matching languages.
          </li>
        )}
        {filtered.map((lang) => (
          <LanguageRow
            key={lang.code}
            option={lang}
            selected={value === lang.code}
            onSelect={() => onChange(lang.code)}
          />
        ))}
      </ul>
    </div>
  )
}

type RowProps = Readonly<{
  option: { code: string; native: string; english: string }
  selected: boolean
  onSelect: () => void
}>

function LanguageRow({ option, selected, onSelect }: RowProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-sm text-left transition-colors ${
          selected ? 'bg-primary/10 text-primary' : 'hover:bg-card'
        }`}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-xs uppercase text-muted-foreground w-8 shrink-0">
            {option.code}
          </span>
          <span className="truncate">
            {option.native}
            {option.native !== option.english && (
              <span className="text-muted-foreground"> · {option.english}</span>
            )}
          </span>
        </span>
        {selected && <Check className="h-4 w-4 shrink-0" aria-hidden="true" />}
      </button>
    </li>
  )
}
