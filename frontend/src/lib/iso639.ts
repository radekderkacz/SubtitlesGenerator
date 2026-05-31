/**
 * Curated subset of ISO 639-1 codes covering the languages WhisperX
 * supports best (per its documentation). Language picker.
 *
 * Native names are written in their own script; English names are the
 * common ASCII forms. The list is alphabetised by English name.
 */
export type LanguageOption = Readonly<{
  code: string
  native: string
  english: string
}>

export const LANGUAGES: ReadonlyArray<LanguageOption> = [
  { code: 'ar', native: 'العربية', english: 'Arabic' },
  { code: 'bg', native: 'Български', english: 'Bulgarian' },
  { code: 'ca', native: 'Català', english: 'Catalan' },
  { code: 'zh', native: '中文', english: 'Chinese' },
  { code: 'hr', native: 'Hrvatski', english: 'Croatian' },
  { code: 'cs', native: 'Čeština', english: 'Czech' },
  { code: 'da', native: 'Dansk', english: 'Danish' },
  { code: 'nl', native: 'Nederlands', english: 'Dutch' },
  { code: 'en', native: 'English', english: 'English' },
  { code: 'et', native: 'Eesti', english: 'Estonian' },
  { code: 'fi', native: 'Suomi', english: 'Finnish' },
  { code: 'fr', native: 'Français', english: 'French' },
  { code: 'de', native: 'Deutsch', english: 'German' },
  { code: 'el', native: 'Ελληνικά', english: 'Greek' },
  { code: 'he', native: 'עברית', english: 'Hebrew' },
  { code: 'hi', native: 'हिन्दी', english: 'Hindi' },
  { code: 'hu', native: 'Magyar', english: 'Hungarian' },
  { code: 'id', native: 'Bahasa Indonesia', english: 'Indonesian' },
  { code: 'it', native: 'Italiano', english: 'Italian' },
  { code: 'ja', native: '日本語', english: 'Japanese' },
  { code: 'ko', native: '한국어', english: 'Korean' },
  { code: 'lv', native: 'Latviešu', english: 'Latvian' },
  { code: 'lt', native: 'Lietuvių', english: 'Lithuanian' },
  { code: 'no', native: 'Norsk', english: 'Norwegian' },
  { code: 'fa', native: 'فارسی', english: 'Persian' },
  { code: 'pl', native: 'Polski', english: 'Polish' },
  { code: 'pt', native: 'Português', english: 'Portuguese' },
  { code: 'ro', native: 'Română', english: 'Romanian' },
  { code: 'ru', native: 'Русский', english: 'Russian' },
  { code: 'sk', native: 'Slovenčina', english: 'Slovak' },
  { code: 'sl', native: 'Slovenščina', english: 'Slovenian' },
  { code: 'es', native: 'Español', english: 'Spanish' },
  { code: 'sv', native: 'Svenska', english: 'Swedish' },
  { code: 'th', native: 'ไทย', english: 'Thai' },
  { code: 'tr', native: 'Türkçe', english: 'Turkish' },
  { code: 'uk', native: 'Українська', english: 'Ukrainian' },
  { code: 'vi', native: 'Tiếng Việt', english: 'Vietnamese' },
]

export const AUTO_DETECT: LanguageOption = {
  code: 'auto',
  native: 'Auto-detect',
  english: 'Auto-detect',
}

export function findLanguage(code: string): LanguageOption | null {
  if (code === AUTO_DETECT.code) return AUTO_DETECT
  return LANGUAGES.find((l) => l.code === code) ?? null
}

/**
 * Fuzzy-search the language list. Returns the original list (in
 * alphabetical order) when the query is empty.
 */
export function filterLanguages(query: string): ReadonlyArray<LanguageOption> {
  const q = query.trim().toLowerCase()
  if (q === '') return LANGUAGES
  return LANGUAGES.filter(
    (l) =>
      l.code.toLowerCase().includes(q) ||
      l.english.toLowerCase().includes(q) ||
      l.native.toLowerCase().includes(q),
  )
}
