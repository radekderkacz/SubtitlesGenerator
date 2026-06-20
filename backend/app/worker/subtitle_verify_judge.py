"""The one I/O part of verification: a single LLM call rating coherence /
faithfulness. Reuses the translation client. Best-effort: any failure collapses
to a soft 'skipped' check."""
from __future__ import annotations

from app.worker.subtitle_verify import SAMPLE_CUES, build_judge_prompt, parse_judge_response, sample_cues


def judge_semantics(cues: list[dict], source_cues: list[dict] | None, model_cfg: dict) -> dict:
    if not cues:
        return {"layer": "semantic", "name": "llm_coherence", "severity": "skipped",
                "detail": "no cues to judge"}
    sampled = sample_cues(cues, SAMPLE_CUES)
    sampled_src = sample_cues(source_cues, SAMPLE_CUES) if source_cues else None
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
        ]}
        raw, _data = _post_translation_with_retries(endpoint, headers, body)
        return parse_judge_response(raw)
    except Exception as e:
        return {"layer": "semantic", "name": "llm_coherence", "severity": "skipped",
                "detail": f"judge unavailable: {type(e).__name__}"}
