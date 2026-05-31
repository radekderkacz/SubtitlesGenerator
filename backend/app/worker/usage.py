"""Translation-response usage parsing + accumulation (SP-3).

Pure, dependency-free, and the single place that knows provider response
shapes. Cost is recorded ONLY when the response reports it (OpenRouter);
the accumulator drops cost to None the moment any contributing call lacks
one — a partial sum would understate and mislead.
"""
from dataclasses import dataclass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def extract_usage(data: dict) -> Usage:
    """Parse an OpenAI-compatible chat-completions response body into Usage.
    Handles the OpenAI shape, OpenRouter's additional ``cost``, and the
    Ollama fallback (top-level ``prompt_eval_count``/``eval_count`` when
    there is no ``usage`` object). Never raises — unrecognized → zeros,
    cost None."""
    try:
        usage = data.get("usage")
        if isinstance(usage, dict):
            prompt = _as_int(usage.get("prompt_tokens"))
            completion = _as_int(usage.get("completion_tokens"))
            total = _as_int(usage.get("total_tokens")) or (prompt + completion)
            cost = usage.get("cost")
            cost = float(cost) if isinstance(cost, (int, float)) else None
            return Usage(prompt, completion, total, cost)
        prompt = _as_int(data.get("prompt_eval_count"))
        completion = _as_int(data.get("eval_count"))
        if prompt or completion:
            return Usage(prompt, completion, prompt + completion, None)
    except Exception:
        pass
    return Usage()


class UsageAccumulator:
    """Sums token counts across calls. ``cost`` stays a running float only
    while every added Usage carried a cost; the first cost-less add makes
    ``cost`` None permanently."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self._cost: float | None = None
        self._seen: bool = False

    def add(self, u: Usage) -> None:
        self.prompt_tokens += u.prompt_tokens
        self.completion_tokens += u.completion_tokens
        self.total_tokens += u.total_tokens
        if not self._seen:
            self._cost = u.cost          # seed (may be None → permanently n/a)
            self._seen = True
        elif self._cost is not None:
            # Once _cost is None post-seed, no branch revives it.
            self._cost = self._cost + u.cost if u.cost is not None else None

    @property
    def cost(self) -> float | None:
        return self._cost
