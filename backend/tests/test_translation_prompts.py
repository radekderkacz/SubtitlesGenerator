"""Tests for the subtitle-aware translation prompt module."""
from app.worker.translation_prompts import (
    CONTEXT_WINDOW_SIZE,
    LANGUAGE_OVERLAYS,
    UNIVERSAL_RULES,
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
    # Tells the model what target language to use.
    assert "pl" in out.lower()
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
    assert "GLOSSARY" not in out_empty


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
