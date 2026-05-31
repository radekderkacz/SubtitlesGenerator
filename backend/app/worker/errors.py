"""Pipeline resilience taxonomy + retry primitive.

The single place that decides what is a *transient* infra error (worth a
retry / requeue) vs a *terminal* one (fail fast — retrying is pointless).
Used by both the in-call retry loops and the job-level requeue chokepoint
so the classification can never drift between layers.
"""
import time
import httpx

# httpx status codes that mean "upstream is momentarily unhealthy".
_TRANSIENT_STATUS = {500, 502, 503, 504, 408, 429}


class TransientPipelineError(Exception):
    """A pipeline step failed on a transient/infra class after its own
    in-call retries were exhausted. Signals the job-level requeue path.
    Carries the originating step name and the underlying cause; its
    message preserves the surfaced upstream text."""

    def __init__(self, step: str, cause: BaseException):
        self.step = step
        self.cause = cause
        super().__init__(f"[{step}] transient failure: {cause}")


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientPipelineError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    return False  # 4xx (non-429), logic/value errors, RuntimeError → terminal


def retry_call(fn, *, step: str, backoffs: list[float]):
    """Run ``fn()``. On a transient error sleep the next ``backoffs``
    entry and retry; on a terminal error re-raise immediately; when the
    transient backoffs are exhausted raise ``TransientPipelineError``.
    ``len(backoffs)`` = number of *retries* (so attempts = len+1)."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — classified next line
            if not is_transient(exc):
                raise
            if attempt >= len(backoffs):
                raise TransientPipelineError(step, exc) from exc
            time.sleep(backoffs[attempt])
            attempt += 1
