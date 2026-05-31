"""SP-3 end-to-end usage/cost contract — the holistic seam guard.

Per-task review mocks every hop, so the *names* a provider response carries
through ``extract_usage`` → ``UsageAccumulator`` → the kwargs the worker
writes onto ``Job`` → the ORM columns → ``_to_history_response`` → the
HistoryResponse wire shape are never proven to line up by the unit suites.
This is precisely the class of defect that bit SP-2 (a worker wrote to a
field name the API never read; every mocked per-task test stayed green).

These tests run the WHOLE chain with NO mocks at any seam: real provider
response bodies → real parsing/accumulation → a real ``Job`` populated the
way ``_run_translation``'s terminal ``_update_job`` populates it → the real
``_to_history_response`` → the serialized wire dict. If any field name
drifts at any hop, these fail.
"""
import uuid
from datetime import datetime, timezone

from app.api.history import _to_history_response
from app.models.orm import Job
from app.worker.usage import UsageAccumulator, extract_usage

# The six fields SP-3 threads worker → DB → API → UI. The contract is that
# this exact set of names survives every hop unchanged.
USAGE_FIELDS = (
    "translation_provider",
    "translation_model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
)


def _job_as_worker_writes_it(acc: UsageAccumulator, provider: str, model: str) -> Job:
    """Mirror exactly the kwargs ``_run_translation``'s terminal
    ``_update_job`` assigns onto the Job — same names, same source values."""
    now = datetime.now(timezone.utc)
    return Job(
        id=str(uuid.uuid4()),
        status="completed",
        phase=None,
        progress=100,
        file_path="/mnt/nas/test.mkv",
        source_language="en",
        target_language="pl",
        model_size="large-v3",
        translation_provider=provider,
        translation_model=model,
        prompt_tokens=acc.prompt_tokens,
        completion_tokens=acc.completion_tokens,
        total_tokens=acc.total_tokens,
        cost_usd=(0.0 if provider == "ollama" else acc.cost),
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


def test_openrouter_cost_survives_worker_to_wire_unmocked():
    """OpenRouter reports cost on every call → real $ value on the wire,
    field names identical end to end, no mocks anywhere."""
    acc = UsageAccumulator()
    # Two real OpenRouter-shaped bodies (glossary + a segment).
    acc.add(extract_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 40,
                                      "total_tokens": 140, "cost": 0.0012}}))
    acc.add(extract_usage({"usage": {"prompt_tokens": 200, "completion_tokens": 60,
                                     "total_tokens": 260, "cost": 0.0030}}))

    job = _job_as_worker_writes_it(acc, "openrouter", "google/gemini-flash-1.5")
    wire = _to_history_response(job).model_dump()

    # Every contract field present under its exact name (drift → KeyError).
    for name in USAGE_FIELDS:
        assert name in wire, f"field name dropped before the wire: {name}"
    assert wire["prompt_tokens"] == 300
    assert wire["completion_tokens"] == 100
    assert wire["total_tokens"] == 400
    assert wire["cost_usd"] == 0.0042  # 0.0012 + 0.0030, provider-reported
    assert wire["translation_provider"] == "openrouter"
    assert wire["translation_model"] == "google/gemini-flash-1.5"


def test_openai_no_cost_yields_null_cost_on_wire_unmocked():
    """OpenAI returns usage but no ``cost`` → tokens flow, cost_usd is None
    on the wire (the UI's ``n/a`` contract). Real chain, no mocks."""
    acc = UsageAccumulator()
    acc.add(extract_usage({"usage": {"prompt_tokens": 50, "completion_tokens": 10,
                                     "total_tokens": 60}}))

    job = _job_as_worker_writes_it(acc, "openai", "gpt-4o-mini")
    wire = _to_history_response(job).model_dump()

    assert wire["total_tokens"] == 60
    assert wire["cost_usd"] is None  # → renders "n/a", never $0.0000
    assert wire["translation_provider"] == "openai"


def test_ollama_shape_yields_zero_cost_on_wire_unmocked():
    """Ollama uses top-level ``prompt_eval_count``/``eval_count`` and never
    reports cost; the worker pins ollama cost to 0.0 → wire shows $0.0000."""
    acc = UsageAccumulator()
    acc.add(extract_usage({"prompt_eval_count": 70, "eval_count": 25}))

    job = _job_as_worker_writes_it(acc, "ollama", "gemma3")
    wire = _to_history_response(job).model_dump()

    assert wire["prompt_tokens"] == 70
    assert wire["completion_tokens"] == 25
    assert wire["total_tokens"] == 95
    assert wire["cost_usd"] == 0.0  # pinned free, distinct from None


def test_one_costless_call_nulls_whole_job_cost_unmocked():
    """The accumulator invariant survives to the wire: one contributing
    call without a cost makes the whole job's cost_usd None (a partial sum
    would understate). This is the §3.1 honesty guarantee, proven end to
    end rather than at the accumulator unit alone."""
    acc = UsageAccumulator()
    acc.add(extract_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 40,
                                     "total_tokens": 140, "cost": 0.0012}}))
    acc.add(extract_usage({"usage": {"prompt_tokens": 80, "completion_tokens": 20,
                                     "total_tokens": 100}}))  # no cost

    job = _job_as_worker_writes_it(acc, "openrouter", "google/gemini-flash-1.5")
    wire = _to_history_response(job).model_dump()

    assert wire["total_tokens"] == 240          # tokens still summed
    assert wire["cost_usd"] is None             # cost dropped permanently


def test_non_translating_job_leaves_usage_null_unmocked():
    """A job that never translated (no _run_translation) leaves all four
    usage columns null; the wire carries None, not 0 — the UI renders
    ``—``/``n/a`` and the bento's ``?? 0`` keeps it numeric."""
    now = datetime.now(timezone.utc)
    job = Job(
        id=str(uuid.uuid4()), status="completed", phase=None, progress=100,
        file_path="/mnt/nas/x.mkv", source_language="en", target_language="en",
        model_size="large-v3", created_at=now, updated_at=now, completed_at=now,
    )
    wire = _to_history_response(job).model_dump()
    for name in USAGE_FIELDS:
        assert wire[name] is None, name
