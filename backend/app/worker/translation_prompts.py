"""Subtitle-aware translation prompts.

Composed at request time:

    SYSTEM = UNIVERSAL_RULES + LANGUAGE_OVERLAYS.get(target_lang, "")

then sent to the OpenAI-compatible chat endpoint as a `system` message
ahead of the user's actual text. Per-segment context from the previous
N translated pairs is appended to the user message so the model keeps
character names, terminology, and register consistent across the film.

The universal rules cover language-agnostic subtitle conventions
distilled from public style guides (Netflix Originals, EBU, ATAA,
SUBTLE). The per-language overlays add typography + grammar rules
specific to that target. Unknown languages fall through to Layer 1 +
the model's defaults and still get a meaningful quality lift over the
previous one-liner prompt.
"""
from __future__ import annotations


UNIVERSAL_RULES = """You are translating subtitle cues from a film or TV show. Follow
these rules strictly:

1. GRAMMAR FIRST. Output must be natural-sounding target-language text.
   When a cue is a complete sentence, produce a grammatically complete
   sentence; when it is a fragment of a sentence that continues in the
   next cue, produce the matching fragment so the sentence flows across
   cues — do NOT force each fragment into a standalone sentence. Never
   drop required articles, verbs, or sentence connectives to save space.
   A broken sentence is worse than a slightly long one.

2. PRESERVE PROPER NOUNS. Character names, nicknames, place names, brand
   names, fictional species, alien terms, and made-up words stay in their
   original spelling. Examples: Spider → Spider; Pandora → Pandora;
   Neytiri → Neytiri. If you are not sure whether a word is a proper noun,
   leave it unchanged. Never invent a translation.

3. MATCH TONE AND REGISTER, NOT WORDS. Translate idioms with the target
   language's idiomatic equivalents. Match the speaker's formality. Match
   profanity intensity (a strong source word maps to a strong target word).
   Don't soften, don't escalate.

4. DON'T ADD CONTENT. No clarifying notes, no "[sound: footsteps]",
   no inline commentary, no quotation marks around the translation.
   Output the translated line and nothing else.

5. SUBTITLE READABILITY. The classical reading-speed target is ~42
   characters per visual line and at most two visual lines per cue. Treat
   this as a *guideline*, not a hard limit: if hitting it would require
   breaking grammar or dropping meaning, exceed it. Grammar and meaning
   always win over line length.

6. CONSISTENCY. If you've translated a recurring term one way earlier in
   this film, keep using that translation. Context cues from previous
   translated lines are provided when available — honour them.

7. WHEN UNSURE, KEEP THE SOURCE WORD. Better an English term than an
   invented or wrong translation.

8. DIALOGUE AND MARKUP. When a cue contains two speakers, keep one line
   per speaker, each starting with the dialogue dash. Keep ♪ markers and
   [bracketed sound labels] in place — translate the words inside them,
   never remove or relocate the markers.

9. THE SOURCE IS SPEECH-RECOGNITION OUTPUT. It may contain mishearings
   and missing punctuation. Translate the evidently intended meaning; if
   a garbled word closely matches a GLOSSARY entry, use the glossary
   spelling. Never invent content to "fix" an unclear line — prefer a
   literal rendering."""


# Per-language overlays. Each is short on purpose — the universal rules
# handle most of the work; overlays add typography + grammar specifics.
# Loaded by ISO 639-1 code. Unknown codes fall through to Layer 1 only.
LANGUAGE_OVERLAYS: dict[str, str] = {
    "pl": """Polish target conventions:
- Use Polish quotation marks: „opening" and "closing".
- Use em-dash (—) for dialogue line starts, not hyphen.
- Drop redundant subject pronouns — Polish verb endings encode person
  (say "Idę do domu", not "Ja idę do domu").
- Track speaker gender when audible from context — past-tense verbs are
  gendered (powiedział vs powiedziała).
- Default to informal "ty" address between peers / family / friends;
  use formal "Pan / Pani" only when the original uses honorifics.
- Preserve all Polish diacritics: ą ć ę ł ń ó ś ź ż.""",

    "de": """German target conventions:
- Use German quotation marks: „opening" and "closing".
- Capitalise ALL nouns, not just proper nouns.
- Default to informal "du" between peers, family, and friends; use
  formal "Sie" only when the source uses titles/honorifics or addresses
  strangers/professional contexts.
- Don't split compound nouns: "Raumschiff", not "Raum-schiff".
- Use ß per current standard orthography (Straße, weiß). Don't substitute ss.
- Subject pronouns are NOT typically dropped (unlike Polish / Spanish).""",

    "es": """Spanish target conventions:
- Use inverted opening marks: ¿pregunta? ¡exclamación!
- Default to neutral Latin American spelling and idioms unless the
  source is clearly Castilian (Spain).
- Default to informal "tú" between peers; use "usted" only when the
  source signals formal address.
- Drop redundant subject pronouns — verb conjugations encode person.
- Preserve Spanish diacritics and ñ.""",

    "fr": """French target conventions:
- Use guillemets « … » with non-breaking spaces inside.
- Use em-dash (—) for dialogue line starts in some styles, or « » per
  film convention — be consistent within the film.
- Default to informal "tu" between peers / family / friends; "vous"
  for strangers and formal contexts (and as the polite singular).
- Preserve all grammatical gender agreement (le / la, accordé / accordée).
- Subject pronouns are required (don't drop "je", "tu", "il", "elle").""",

    "it": """Italian target conventions:
- Use guillemets « … » or curly quotes — match the source style.
- Default to informal "tu" between peers; "Lei" (capitalised) for formal.
- Use elision apostrophes naturally: l'amico, dell'auto, un'idea.
- Subject pronouns commonly dropped — verbs encode person.""",

    "pt": """Portuguese target conventions:
- Distinguish Brazilian Portuguese (PT-BR) from European (PT-PT).
  Default to PT-BR unless context signals otherwise.
- PT-BR uses "você" as the default singular address; PT-PT uses "tu"
  more commonly between peers.
- Subject pronouns frequently dropped — verbs encode person.
- Preserve Portuguese diacritics: ã õ ç é ê á à etc.""",

    "en": """English target conventions:
- Use standard double quotes "…" for direct speech.
- US English spelling and idioms by default unless the source content
  is clearly British (in which case match BrE).
- Preserve contractions in dialogue ("it's", "don't", "we'll") —
  expand them only for very formal speech.
- Use en-dash (–) for ranges, em-dash (—) for dialogue / break.""",

    "ja": """Japanese target conventions:
- Use 「…」 for direct speech, 『…』 for nested quotes.
- Preserve honorifics on character names: -san, -kun, -chan, -sama,
  -sensei. They are part of the name, not a translatable suffix.
- Choose verb register (です/ます polite vs. casual だ/plain) to match
  each speaker's register in the source.
- No spaces between words. Punctuation: 、 for comma, 。 for period.""",

    "zh": """Chinese target conventions:
- Default to Simplified Chinese unless the source is clearly Traditional.
- Simplified uses straight double quotes "…" for speech; Traditional
  uses 「…」.
- No plural inflection on nouns — pluralisation is expressed lexically.
- Use aspectual particles (了, 过, 着) for tense / aspect; Chinese has no
  verb conjugation.
- Use Chinese punctuation: ， 。 ？ ！ — not Latin punctuation.""",

    "ru": """Russian target conventions:
- Use « … » quotation marks (or curly „ … " in some styles — be consistent).
- Default to informal "ты" between peers / family / friends; "Вы"
  (capitalised when addressing a single person) for strangers / formal.
- Past-tense verbs are gendered (сказал vs сказала) — track speaker gender
  from audible context.
- Preserve Cyrillic script and stress markers if present in the source.""",
}


# Number of (source, target) pairs from earlier in the film to include
# as continuity context on each call. Was dropped to 1 when translation
# ran per-cue (context tripled per-call latency on local models); batching
# amortizes the prompt across 10 cues, so 3 pairs of cross-batch context
# costs ~90 extra tokens per ~10-cue call — cheap for the gender/register
# continuity it buys (Polish gendered past tense, tu/vous tracking).
CONTEXT_WINDOW_SIZE = 3

# ISO-639-1 → English language name. Weaker models follow "translate to
# Polish" far more reliably than "translate to pl"; the names also label
# continuity pairs with the real source language (a Japanese film's lines
# used to be labelled "EN:").
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "pl": "Polish", "de": "German", "es": "Spanish",
    "fr": "French", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "nl": "Dutch",
    "cs": "Czech", "uk": "Ukrainian", "ar": "Arabic", "hi": "Hindi",
    "tr": "Turkish", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "fi": "Finnish", "el": "Greek", "hu": "Hungarian", "ro": "Romanian",
    "vi": "Vietnamese", "th": "Thai", "he": "Hebrew", "id": "Indonesian",
    "sk": "Slovak", "bg": "Bulgarian", "hr": "Croatian", "sr": "Serbian",
    "ca": "Catalan",
}


def language_name(code: str | None) -> str:
    """Human-readable name for an ISO-639-1 code; unknown codes pass through."""
    cleaned = (code or "").strip()
    return LANGUAGE_NAMES.get(cleaned.lower(), cleaned)


def _context_block(
    context_pairs: list[tuple[str, str]],
    target_language: str,
    source_language: str | None,
) -> list[str]:
    """Render continuity pairs with real language-name labels."""
    src_label = (language_name(source_language).upper() or "SOURCE") if source_language else "SOURCE"
    tgt_label = language_name(target_language).upper() or target_language.upper()
    lines = ["Previous lines from this film for continuity reference:"]
    for src, tgt in context_pairs:
        lines.append(f"  {src_label}: {src}")
        lines.append(f"  {tgt_label}: {tgt}")
    lines.append("")
    return lines


def _bible_block(bible: dict) -> str:
    """Render the film bible (characters + genders, setting, register, pinned
    term translations) for the system prompt. Character genders directly
    attack gendered-verb errors (Polish/Russian past tense); pinned terms give
    cue 847 the same translation cue 12 chose."""
    lines: list[str] = ["FILM CONTEXT:"]
    setting = (bible.get("setting") or "").strip()
    if setting:
        lines.append(f"- Setting: {setting}")
    register = (bible.get("register") or "").strip()
    if register:
        lines.append(f"- Dialogue register: {register}")
    characters = [c for c in (bible.get("characters") or [])
                  if isinstance(c, dict) and c.get("name")]
    if characters:
        rendered = ", ".join(
            f"{c['name']} ({c['gender']})" if c.get("gender") else str(c["name"])
            for c in characters
        )
        lines.append(f"- Characters (use these genders for gendered grammar): {rendered}")
    terms = bible.get("terms") or {}
    if terms:
        pinned = "; ".join(f"{src} → {tgt}" for src, tgt in terms.items())
        lines.append(f"- ESTABLISHED TRANSLATIONS (always use these): {pinned}")
    return "\n".join(lines)


def build_system_prompt(
    target_language: str | None,
    glossary: list[str] | None = None,
    bible: dict | None = None,
) -> str:
    """Compose the system message: universal rules + language overlay +
    optional glossary.

    The glossary is a list of proper nouns / fictional terms / character names
    pre-extracted from the full transcript in a single upfront LLM call (see
    ``_extract_glossary`` in tasks.py). Injecting them as an explicit "keep
    these unchanged" list catches long-range consistency issues that the
    per-call context window can't — a name introduced in cue 12 and recurring
    in cue 847 is still in the glossary, while it's long out of the context
    window.

    The glossary block is appended at the end so the prior rules (which the
    LLM server likely prefix-caches) stay in identical position across every
    call.
    """
    overlay = LANGUAGE_OVERLAYS.get((target_language or "").lower(), "")
    parts = [UNIVERSAL_RULES]
    if overlay:
        parts.append(overlay)
    if bible:
        block = _bible_block(bible)
        if block != "FILM CONTEXT:":
            parts.append(block)
    if glossary:
        glossary_block = (
            "GLOSSARY — the following words / names appear in this film and "
            "must be kept exactly as written in your translation, without "
            "translation, transliteration, or case changes:\n"
            + ", ".join(sorted(set(glossary)))
        )
        parts.append(glossary_block)
    return "\n\n".join(parts)


def build_glossary_extraction_prompt(joined_source: str) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for the one-shot glossary
    extraction call. Output contract: model returns a JSON array of strings,
    nothing else."""
    system = (
        "You extract proper nouns from film subtitle transcripts so they can "
        "be preserved verbatim during translation. Return ONLY a JSON array "
        "of strings — no commentary, no markdown, no surrounding object."
    )
    user = (
        "Extract every proper noun from this transcript that should NOT be "
        "translated to another language. Include:\n"
        "- Character names and nicknames (Jake, Spider, Neytiri)\n"
        "- Place names (Pandora, Hell's Gate)\n"
        "- Fictional species / factions (Na'vi, RDA)\n"
        "- Made-up or technical terms (unobtainium, AMP suit)\n"
        "- Brand names\n\n"
        "Skip ordinary words even if capitalised at sentence start. Skip "
        "names of real-world places that have established target-language "
        "translations (e.g. London → Londyn in Polish).\n\n"
        "Output format: a JSON array of strings, deduplicated, in the case "
        "the term appears in the transcript. Example: "
        '["Jake", "Spider", "Pandora", "Na\'vi"]\n\n'
        "Transcript:\n" + joined_source
    )
    return system, user


def build_bible_extraction_prompt(chunk: str, target_language: str) -> tuple[str, str]:
    """(system, user) for one film-bible extraction call over a transcript
    window. Output contract: a single JSON object, nothing else."""
    system = (
        "You analyze film subtitle transcripts so a translator can stay "
        "consistent. Return ONLY a raw JSON object — no commentary, no "
        "markdown fences."
    )
    user = (
        "From this transcript excerpt, extract:\n"
        '- "names": proper nouns to keep verbatim (characters, places, '
        "brands, fictional terms)\n"
        '- "characters": [{"name": ..., "gender": "male"|"female"|"unknown"}] '
        "for every speaking character whose gender is evident\n"
        '- "terms": {source term: %s translation} for recurring translatable '
        "terms (titles, nicknames, jargon) that must stay consistent\n"
        '- "setting": one sentence describing the story world\n'
        '- "register": a short description of the dialogue register '
        "(formal/informal, era, profession)\n\n"
        "Output format: "
        '{"names": [...], "characters": [...], "terms": {...}, '
        '"setting": "...", "register": "..."}\n\n'
        "Transcript:\n%s"
    ) % (language_name(target_language), chunk)
    return system, user


def build_user_prompt(
    text: str,
    target_language: str,
    context_pairs: list[tuple[str, str]] | None = None,
    source_language: str | None = None,
) -> str:
    """Compose the user message: prior translated pairs (if any) + the
    current line to translate.

    ``context_pairs`` is a list of (source, translation) tuples from the
    previous N cues in this film, oldest first. They're included verbatim
    so the model can keep names, terminology, and register consistent.
    """
    lines: list[str] = []
    if context_pairs:
        lines.extend(_context_block(context_pairs, target_language, source_language))
    lines.append(
        f"Translate the next line to {language_name(target_language)}. "
        f"Output only the translated line, with no commentary, no quotes, "
        f"and no preamble."
    )
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


BATCH_OUTPUT_CONTRACT = (
    "You are now translating a NUMBERED LIST of consecutive subtitle cues from "
    "the same film, in original order — not a single line. USE CROSS-CUE "
    "CONTEXT: resolve pronouns, grammatical gender, and formality (ty/Pan, "
    "du/Sie, tu/vous) from the surrounding cues and the continuity lines when "
    "present; when a sentence continues across cues, translate it as one "
    "flowing sentence split at the same point. Output each translation on "
    "its own line, prefixed with the SAME number and a period (e.g. '1.', '2.'), in "
    "the same order, exactly one line per input cue, and nothing else — no "
    "commentary, no blank lines, no quotes, no reasoning."
)


def build_batch_system_prompt(
    target_language: str,
    glossary: list[str] | None = None,
    bible: dict | None = None,
) -> str:
    """Per-cue system prompt (rules + per-language overlay + film bible +
    glossary) plus a numbered-list output contract, so one call can translate
    many cues."""
    return (build_system_prompt(target_language, glossary=glossary, bible=bible)
            + "\n\n" + BATCH_OUTPUT_CONTRACT)


def build_batch_user_prompt(
    texts: list[str],
    target_language: str,
    context_pairs: list[tuple[str, str]] | None = None,
    source_language: str | None = None,
    story_so_far: str | None = None,
) -> str:
    """Compose the batch user message: optional story summary + continuity
    context, then the numbered source cues (each flattened to one line —
    reflow re-wraps later)."""
    lines: list[str] = []
    if story_so_far:
        lines.append(f"STORY SO FAR (for pronoun/gender/register continuity): {story_so_far}")
        lines.append("")
    if context_pairs:
        lines.extend(_context_block(context_pairs, target_language, source_language))
    lines.append(
        f"Translate the following {len(texts)} numbered lines to "
        f"{language_name(target_language)}. "
        f"Output each translation on its own line prefixed with its number "
        f"(1., 2., …), same order, one per input line, nothing else."
    )
    lines.append("")
    for n, t in enumerate(texts, start=1):
        flat = " ".join(t.splitlines()).strip()
        lines.append(f"{n}. {flat}")
    return "\n".join(lines)
