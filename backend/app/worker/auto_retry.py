"""Automatic free retry after a failed verification.

When a fresh generation ends with verification_status='fail' and the job's
backend snapshot is cost-free to re-run (self-hosted transcription, local
Ollama translation), the worker queues exactly one regeneration instead of
leaving the broken output flagged. Paid profiles keep the flag-and-stop
behavior — an automatic retry must never spend tokens.
"""
import os

# Lineage marker on the cloned job's ``source`` field: "auto-regen:<original-id>".
# A job whose source carries this prefix never auto-retries again, which caps
# the chain at exactly one automatic attempt per original job.
AUTO_RETRY_SOURCE_PREFIX = "auto-regen:"


def is_cost_free_backend(backend: dict, target_language: str | None) -> bool:
    """Conservative "free to re-run" heuristic.

    Transcription: a keyless endpoint is assumed self-hosted — hosted ASR
    (Groq/OpenAI) always requires an API key. Translation: only Ollama is
    treated as free, matching the worker's cost model (cost_usd is forced to
    0.0 for ollama), or no translation at all. Anything ambiguous counts as
    paid so a retry never silently spends money.
    """
    if backend.get("transcription_api_key"):
        return False
    if target_language and backend.get("translation_provider") != "ollama":
        return False
    return True


def should_auto_retry(job) -> bool:
    """One free retry per original job.

    Qualifies only when: the kill switch is off, the job is not itself an
    auto-retry, verification hard-failed (not warn/error), and the job's own
    backend snapshot is cost-free per is_cost_free_backend().
    """
    if os.environ.get("SUBGEN_DISABLE_AUTO_RETRY"):
        return False
    if (getattr(job, "source", "") or "").startswith(AUTO_RETRY_SOURCE_PREFIX):
        return False
    if job.verification_status != "fail":
        return False
    backend = getattr(job, "backend_profile", None)
    if not backend:
        return False
    return is_cost_free_backend(backend, job.target_language)
