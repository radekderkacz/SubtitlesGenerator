"""Tests for the subtitle-aware translation prompt module."""
from app.worker.translation_prompts import (
    CONTEXT_WINDOW_SIZE,
    LANGUAGE_OVERLAYS,
    UNIVERSAL_RULES,
    build_batch_system_prompt,
    build_batch_user_prompt,
    build_glossary_extraction_prompt,
    build_system_prompt,
    build_user_prompt,
)


def test_universal_rules_cover_the_critical_subtitle_conventions():
    """The whole point of Layer 1 is to fix the proper-noun-translation bug.
    These assertions are the load-bearing ones — if any of them break, the
    quality fix that motivated this module is silently regressing."""
    rules = UNIVERSAL_RULES.lower()
    # Proper nouns are the user-reported pain point (Jake → Kuba).
    assert "proper noun" in rules
    assert "preserve" in rules or "keep" in rules
    # Tone / register, not literal translation.
    assert "tone" in rules or "register" in rules
    # Don't add interpretive content.
    assert "don't add" in rules or "do not add" in rules
    # Subtitle readability — the 42-char target is mentioned as guidance,
    # but the rule explicitly subordinates it to grammar (a regression
    # would put "42" without the grammar-first qualifier).
    assert "42" in UNIVERSAL_RULES
    # Grammar-first rule: surfaced after the first production run produced
    # over-compressed clipped Polish ("Postrzel wracamy po spider").
    assert "grammar" in rules
    # Continuity / consistency rule.
    assert "consist" in rules
    # When unsure, keep the source word.
    assert "when unsure" in rules or "not sure" in rules


def test_each_supported_language_overlay_is_non_empty():
    """Every overlay must add at least one concrete convention beyond the
    universal layer — otherwise it shouldn't exist."""
    assert len(LANGUAGE_OVERLAYS) >= 10, "expected ≥10 language overlays"
    for code, overlay in LANGUAGE_OVERLAYS.items():
        assert len(code) == 2, f"language code {code!r} is not ISO-639-1 (2 letters)"
        assert len(overlay.strip()) > 100, f"{code} overlay is suspiciously short"


def test_polish_overlay_mentions_polish_specific_conventions():
    """Polish was the test case that surfaced the original bug — extra
    care that the overlay actually addresses the things that went wrong."""
    pl = LANGUAGE_OVERLAYS["pl"].lower()
    # The Polish-specific typography that the prior one-liner missed.
    assert "„" in LANGUAGE_OVERLAYS["pl"]  # Polish opening quotation mark
    # Drop redundant pronouns (verb endings encode person).
    assert "subject pronoun" in pl
    # Gendered past-tense verbs require knowing the speaker's gender.
    assert "gender" in pl
    # Informal "ty" is the default for peer dialogue.
    assert "ty" in pl


def test_german_overlay_specifies_noun_capitalisation_and_du_sie():
    de = LANGUAGE_OVERLAYS["de"].lower()
    assert "capitalise" in de or "capitalize" in de
    assert "du" in de
    assert "sie" in de


def test_build_system_prompt_includes_universal_and_overlay_for_known_language():
    out = build_system_prompt("pl")
    assert UNIVERSAL_RULES in out
    assert LANGUAGE_OVERLAYS["pl"] in out


def test_build_system_prompt_falls_back_to_universal_only_for_unknown_language():
    out = build_system_prompt("xx")
    assert out == UNIVERSAL_RULES


def test_build_system_prompt_accepts_uppercase_or_mixed_case_codes():
    """ISO codes can arrive as 'PL' or 'Pl' depending on UI source — overlay
    lookup is case-insensitive."""
    out = build_system_prompt("PL")
    assert LANGUAGE_OVERLAYS["pl"] in out
    out2 = build_system_prompt("De")
    assert LANGUAGE_OVERLAYS["de"] in out2


def test_build_system_prompt_handles_none_or_empty_language():
    """target_language=None (no translation requested) shouldn't crash —
    return just the universal layer."""
    assert build_system_prompt(None) == UNIVERSAL_RULES
    assert build_system_prompt("") == UNIVERSAL_RULES


def test_build_user_prompt_includes_the_source_text():
    out = build_user_prompt("Hello world", "pl")
    assert "Hello world" in out
    # Tells the model what target language to use (full name since WS3).
    assert "polish" in out.lower()
    # Reminds the model to output only the translation.
    assert "only" in out.lower()


def test_build_user_prompt_inlines_context_pairs_when_provided():
    """Continuity context is the second-biggest quality lever after the
    system prompt — it's how the model learns 'Spider → Spider' once and
    then keeps doing it."""
    pairs = [
        ("Spider, get over here", "Spider, chodź tutaj"),
        ("Jake's looking for you", "Jake cię szuka"),
    ]
    out = build_user_prompt("Spider, did you hear me?", "pl", context_pairs=pairs)
    # All four prior strings appear verbatim in the prompt.
    for s in (
        "Spider, get over here",
        "Spider, chodź tutaj",
        "Jake's looking for you",
        "Jake cię szuka",
    ):
        assert s in out
    # The current line to translate is at the end.
    assert out.rstrip().endswith("Spider, did you hear me?")


def test_build_user_prompt_omits_context_block_when_no_pairs_supplied():
    out = build_user_prompt("Hello", "pl")
    # The "Previous lines" header only appears when context is included.
    assert "Previous lines" not in out
    assert "Hello" in out


def test_build_system_prompt_appends_glossary_when_supplied():
    """The glossary is the third layer (after universal rules + language
    overlay) that pins long-range proper nouns the per-call context window
    can't reach. It must be appended LAST so the prefix (universal + overlay)
    stays byte-identical across every call — that's what lets the LLM server
    prefix-cache it."""
    out = build_system_prompt("pl", glossary=["Spider", "Pandora", "Na'vi"])
    # All three components appear, in order.
    assert UNIVERSAL_RULES in out
    assert LANGUAGE_OVERLAYS["pl"] in out
    # Each glossary term appears verbatim.
    assert "Spider" in out
    assert "Pandora" in out
    assert "Na'vi" in out
    # The glossary block sits at the END (so the cacheable prefix is stable).
    assert out.endswith("Pandora") or out.endswith("Spider") or out.endswith("Na'vi") or \
        out.rstrip().endswith(("Spider", "Pandora", "Na'vi"))
    # The instruction wording makes the "do not translate" intent explicit.
    lower = out.lower()
    assert "glossary" in lower
    assert "kept exactly" in lower or "without translation" in lower or "preserve" in lower


def test_build_system_prompt_handles_empty_glossary():
    """An empty list means we extracted but found nothing — drop the glossary
    block entirely so the prompt is byte-identical to the no-glossary case
    (else prefix cache misses for free)."""
    out_none = build_system_prompt("pl", glossary=None)
    out_empty = build_system_prompt("pl", glossary=[])
    assert out_none == out_empty
    # No glossary BLOCK is appended (rule 9 may mention the word itself).
    assert "GLOSSARY —" not in out_empty


def test_build_system_prompt_deduplicates_glossary_terms():
    """Extraction can return duplicates (case-sensitive). Dedupe on the
    composer side so callers don't have to."""
    out = build_system_prompt("pl", glossary=["Spider", "Spider", "Pandora"])
    # "Spider" should appear once in the glossary block, not twice.
    glossary_block = out.rsplit("GLOSSARY", 1)[-1]
    assert glossary_block.count("Spider") == 1


def test_build_glossary_extraction_prompt_returns_system_and_user_pair():
    """The extraction call uses a different prompt pair than per-cue translation:
    system tells the model to return JSON only, user supplies the transcript and
    spells out what counts as a proper noun."""
    transcript = "Spider, get back!\nJake is on Pandora.\nThe Na'vi watch."
    system, user = build_glossary_extraction_prompt(transcript)
    # System pins the output format.
    assert "JSON" in system
    assert "array" in system.lower()
    # User makes the inclusion/exclusion criteria explicit.
    lower_user = user.lower()
    assert "proper noun" in lower_user
    # Concrete examples of each category we want.
    assert "character" in lower_user or "name" in lower_user
    assert "place" in lower_user
    assert "fictional" in lower_user or "made-up" in lower_user or "made up" in lower_user
    # Skip-list of things we explicitly DON'T want, like sentence-start
    # capitalisations and real-world place names that DO have translations.
    assert "skip" in lower_user or "exclude" in lower_user
    # Transcript itself is in the user message.
    assert transcript in user


def test_build_glossary_extraction_prompt_includes_a_concrete_output_example():
    """Models follow output format instructions much better when given a
    one-shot example. The JSON-array-of-strings example pins down case
    handling (proper-noun-cased) and primes the model to emit raw JSON
    rather than a markdown code fence."""
    _, user = build_glossary_extraction_prompt("ignored")
    # Example uses bracket-quoted JSON, not markdown code fence.
    assert "[" in user and "]" in user
    # An example term appears literally so the model has a concrete pattern.
    assert "Jake" in user or "Spider" in user or "Pandora" in user


def test_context_window_size_is_a_sane_default():
    """1-3 pairs is the practical range. Initial value was 3, but production
    measurements on gpt-oss:20b showed ~9 sec/segment vs ~2.4 sec/segment
    without any context — the layered prompt + 3 pairs roughly tripled
    per-call latency. Dropped to 1 pair to keep continuity for adjacent
    cues without quadrupling input tokens. Anything past ~5 turns each
    call into a 1k-token prompt for a 20-token answer.
    """
    assert 1 <= CONTEXT_WINDOW_SIZE <= 5


def test_batch_system_prompt_extends_per_cue_rules_with_list_contract():
    s = build_batch_system_prompt("pl", glossary=["Na'vi"])
    assert build_system_prompt("pl", glossary=["Na'vi"]) in s
    assert "numbered" in s.lower()
    assert "Na'vi" in s


def test_batch_user_prompt_numbers_each_line():
    u = build_batch_user_prompt(["Hello.", "How are you?"], "pl")
    assert "1. Hello." in u
    assert "2. How are you?" in u


def test_batch_user_prompt_includes_context_pairs():
    u = build_batch_user_prompt(["Hi."], "pl", context_pairs=[("Run!", "Biegnij!")])
    assert "Run!" in u and "Biegnij!" in u


def test_batch_user_prompt_flattens_multiline_source():
    u = build_batch_user_prompt(["line one\nline two"], "pl")
    assert "1. line one line two" in u


# ---------------------------------------------------------------------------
# WS3 (2026-07 audit): language names, cross-cue context, dialogue/ASR rules
# ---------------------------------------------------------------------------

def test_language_name_maps_iso1_to_english_name():
    from app.worker.translation_prompts import language_name
    assert language_name("pl") == "Polish"
    assert language_name("PL") == "Polish"
    assert language_name("xx") == "xx"
    assert language_name(None) == ""


def test_prompts_use_full_language_names():
    out = build_user_prompt("Hello", "pl")
    assert "Polish" in out
    bout = build_batch_user_prompt(["Hello"], "pl")
    assert "Polish" in bout


def test_context_pairs_label_uses_source_language_name():
    pairs = [("Hej", "Hallo")]
    out = build_batch_user_prompt(["Cześć"], "de", context_pairs=pairs, source_language="pl")
    assert "POLISH:" in out
    assert "EN:" not in out
    per_cue = build_user_prompt("Cześć", "de", context_pairs=pairs, source_language="pl")
    assert "POLISH:" in per_cue


def test_context_pairs_label_falls_back_to_source():
    out = build_batch_user_prompt(["Hi"], "de", context_pairs=[("a", "b")], source_language=None)
    assert "SOURCE:" in out
    assert "EN:" not in out


def test_batch_contract_demands_cross_cue_context():
    from app.worker.translation_prompts import BATCH_OUTPUT_CONTRACT
    low = BATCH_OUTPUT_CONTRACT.lower()
    assert "independently" not in low
    assert "gender" in low
    assert "pronoun" in low
    assert "formality" in low


def test_universal_rules_cover_dialogue_music_and_asr_tolerance():
    low = UNIVERSAL_RULES.lower()
    assert "♪" in UNIVERSAL_RULES
    assert "dialogue" in low
    assert "speech-recognition" in low or "speech recognition" in low
    assert "fragment" in low


def test_context_window_is_three():
    assert CONTEXT_WINDOW_SIZE == 3


# ---------------------------------------------------------------------------
# WS8 (2026-07 audit): film bible + story-so-far context
# ---------------------------------------------------------------------------

def test_bible_extraction_prompt_asks_for_structured_json():
    from app.worker.translation_prompts import build_bible_extraction_prompt
    system, user = build_bible_extraction_prompt("JAKE: Get down!\nNEYTIRI: Run.", "pl")
    low = (system + user).lower()
    assert "json" in low
    assert "character" in low
    assert "gender" in low
    assert "register" in low
    assert "JAKE: Get down!" in user


def test_system_prompt_renders_bible_blocks():
    bible = {
        "names": ["Pandora", "Na'vi"],
        "characters": [{"name": "Jake", "gender": "male"},
                       {"name": "Neytiri", "gender": "female"}],
        "terms": {"the Colonel": "Pułkownik"},
        "setting": "Military sci-fi on an alien moon.",
        "register": "informal military banter",
    }
    out = build_system_prompt("pl", glossary=["Pandora", "Na'vi"], bible=bible)
    assert "Jake (male)" in out
    assert "Neytiri (female)" in out
    assert "the Colonel" in out and "Pułkownik" in out
    assert "Military sci-fi" in out
    assert "informal military banter" in out
    # prefix-cache stability: universal rules still lead
    assert out.startswith(UNIVERSAL_RULES.split("\n")[0])


def test_system_prompt_without_bible_unchanged():
    assert build_system_prompt("pl", glossary=["X"]) == build_system_prompt(
        "pl", glossary=["X"], bible=None)


def test_batch_user_prompt_carries_story_so_far():
    out = build_batch_user_prompt(["Line one."], "pl",
                                  story_so_far="Jake infiltrated the base.")
    assert "STORY SO FAR" in out
    assert "Jake infiltrated the base." in out
