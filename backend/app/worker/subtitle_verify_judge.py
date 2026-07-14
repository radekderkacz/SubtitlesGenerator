"""The one I/O part of verification: a single LLM call rating coherence /
faithfulness. Reuses the translation client. Best-effort: any failure collapses
to a soft 'skipped' check."""
from __future__ import annotations

from app.worker.subtitle_verify import (
    SAMPLE_CUES,
    build_judge_prompt,
    pair_cues_by_time,
    parse_judge_response,
    sample_cues,
)

# Deterministic scoring — same subtitles must yield the same verdict on
# re-verify, so the judge runs at temperature 0.
JUDGE_TEMPERATURE = 0.0


def judge_semantics(cues: list[dict], source_cues: list[dict] | None, model_cfg: dict) -> dict:
    if not cues:
        return {"layer": "semantic", "name": "llm_coherence", "severity": "skipped",
                "detail": "no cues to judge"}
    sampled = sample_cues(cues, SAMPLE_CUES)
    sampled_src = None
    if source_cues:
        # Pair by nearest start time — independent index sampling mis-pairs
        # the moment source/target cue counts differ, making the judge rate
        # lines that were never translations of each other.
        pairs = pair_cues_by_time(sampled, source_cues)
        sampled_src = [s for s, _t in pairs]
        sampled = [t for _s, t in pairs]
    system, user = build_judge_prompt(sampled, sampled_src)
    try:
        from app.worker.tasks import _resolve_translation_endpoint, _post_translation_with_retries
        actual_model, endpoint = _resolve_translation_endpoint(model_cfg["mapped_model"], model_cfg.get("base_url"))
        headers = {"Content-Type": "application/json"}
        if model_cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {model_cfg['api_key']}"
        body = {"model": actual_model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"/no_think {user}"},
        ], "temperature": JUDGE_TEMPERATURE}
        raw, _data = _post_translation_with_retries(endpoint, headers, body)
        return parse_judge_response(raw)
    except Exception as e:
        # A configured judge that can't run must be VISIBLE — 'skipped' ranks
        # as ok and silently upgraded outages to passes (2026-07 audit).
        return {"layer": "semantic", "name": "llm_coherence", "severity": "warn",
                "detail": f"judge unavailable — semantic layer unverified ({type(e).__name__})"}
