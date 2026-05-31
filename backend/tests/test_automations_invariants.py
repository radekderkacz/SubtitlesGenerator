"""Holistic grep guards for cross-cutting Automations invariants.

These tests enforce architectural constraints that cannot be tested at the
unit level. They scan the source tree and fail fast if any invariant is
violated.

Invariants:
  1. CHOKEPOINT: From trigger-derived code, `enqueue_job` is imported/called
     only from trigger_executor.py. No other automations module calls it
     directly.

  2. NO BROAD EXCEPT: New automations modules must not use `except Exception:`
     (bare broad catch). Narrow exception clauses only.

  3. NO WINDOW.X: Frontend automations components must not use `window.X`
     (use `globalThis.X` instead, which is safer in non-browser environments).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = ROOT / "backend" / "app"
FRONTEND_AUTOMATIONS = ROOT / "frontend" / "src" / "components" / "Automations"
FRONTEND_PAGE_AUTOMATIONS = ROOT / "frontend" / "src" / "pages" / "Automations"

# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1: single enqueue_job chokepoint
# ─────────────────────────────────────────────────────────────────────────────

# Files that are ALLOWED to import/call enqueue_job from trigger context
ALLOWED_ENQUEUE_CALLERS = {
    "trigger_executor.py",  # the single chokepoint — calls enqueue_job
    "job_service.py",       # defines enqueue_job
}

# Automations service/api modules that must NOT call enqueue_job
AUTOMATIONS_MODULES = [
    BACKEND_APP / "services" / "cron_scheduler.py",
    BACKEND_APP / "services" / "watcher.py",
    BACKEND_APP / "services" / "trigger_service.py",
    BACKEND_APP / "api" / "triggers.py",
    BACKEND_APP / "api" / "webhooks.py",
]


def test_only_trigger_executor_calls_enqueue_job():
    """Non-executor automations modules must not import or call enqueue_job."""
    violations = []
    for path in AUTOMATIONS_MODULES:
        if not path.exists():
            continue
        text = path.read_text()
        # Match both `from ... import enqueue_job` and `enqueue_job(`
        if re.search(r'\benqueue_job\b', text):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == [], (
        f"enqueue_job called outside the allowed chokepoint: {violations}\n"
        "All trigger-derived job submissions must go through "
        "trigger_executor.dispatch_event, which is the single caller of "
        "enqueue_job from automations code."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1b: generate_subtitles.delay() callsite allowlist.
#
# enqueue_job is now atomic — it dispatches the Celery task itself. Any
# OTHER caller of `.delay()` must be a known re-dispatch path (retry,
# orphan recovery). A new `.delay()` call outside this list is either a
# double-dispatch bug or a new caller that bypassed the chokepoint and
# must be reviewed.
#
# This invariant catches the bug class that produced four bugs in 2 days:
# "feature ships, the chokepoint claim turns out to be advisory only,
# new caller silently breaks the contract."
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_DELAY_CALLERS = {
    BACKEND_APP / "services" / "job_service.py",         # the chokepoint itself
    BACKEND_APP / "api" / "jobs.py",                     # retry endpoint (re-dispatch)
    BACKEND_APP / "worker" / "orphan_recovery.py",       # re-dispatch on worker restart
}

DELAY_PATTERN = re.compile(r'\bgenerate_subtitles\.delay\s*\(')


def test_generate_subtitles_delay_callsite_allowlist():
    """Any new `.delay()` of generate_subtitles outside the allowlist is
    either a double-dispatch bug (enqueue_job already does it) or a caller
    bypassing the chokepoint. Add to ALLOWED_DELAY_CALLERS only with a
    clear architectural reason — and add a regression test next to it."""
    violations: list[str] = []
    for path in BACKEND_APP.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        if path == BACKEND_APP / "worker" / "tasks.py":
            # tasks.py defines the task; the `@celery_app.task` decorator
            # doesn't trip the pattern anyway.
            continue
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), 1):
            if DELAY_PATTERN.search(line) and path not in ALLOWED_DELAY_CALLERS:
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert violations == [], (
        "generate_subtitles.delay() called outside the allowlist:\n"
        + "\n".join(violations)
        + "\nenqueue_job dispatches automatically — drop the redundant .delay() "
        "call, OR if this is a re-dispatch path (retry/orphan), add the file "
        "to ALLOWED_DELAY_CALLERS in test_automations_invariants.py with a "
        "comment explaining why."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1c: httpx clients in long-running worker code must live inside
# a context manager.
#
# Worker pipeline tasks open httpx.Client / httpx.AsyncClient for the remote
# transcription API and Ollama translation API. A bare `httpx.Client(...)`
# without `with` (or `async with`) leaks the underlying socket + connection
# pool on every call — over the lifetime of a Celery child that processes
# 10s of jobs, this exhausts FDs and/or poisons NFS access (the 2026-05-29
# Landman-batch failure pattern). `worker_max_tasks_per_child=1` is the
# pragmatic safety net; this invariant prevents the leak class from
# re-entering the worker codebase at all.
# ─────────────────────────────────────────────────────────────────────────────

WORKER_FILES_FOR_HTTP_CHECK = [
    BACKEND_APP / "worker" / "tasks.py",
    BACKEND_APP / "worker" / "orphan_recovery.py",
    BACKEND_APP / "services" / "trigger_executor.py",
    BACKEND_APP / "services" / "cron_scheduler.py",
    BACKEND_APP / "services" / "watcher.py",
    BACKEND_APP / "services" / "jellyfin.py",
]

# Lines starting an httpx client. We require the same line to also contain
# a `with` keyword (covers `with httpx.Client(...)`, `async with httpx.AsyncClient(...)`,
# `with httpx.AsyncClient(...) as c:`, and the multi-arg variants).
_HTTPX_CLIENT_CTOR = re.compile(r'httpx\.(Async)?Client\s*\(')
_HTTPX_IN_CONTEXT = re.compile(r'\bwith\b.*httpx\.(Async)?Client\s*\(')


def test_httpx_clients_in_worker_use_context_manager():
    """Every httpx.Client/AsyncClient instantiation in worker/services
    code must be in `with ... :` or `async with ... :`. Anything else is
    a session leak waiting to surface."""
    violations: list[str] = []
    for path in WORKER_FILES_FOR_HTTP_CHECK:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _HTTPX_CLIENT_CTOR.search(line) and not _HTTPX_IN_CONTEXT.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert violations == [], (
        "httpx client created outside `with`/`async with` (will leak sockets):\n"
        + "\n".join(violations)
        + "\nWrap with `with httpx.Client(...) as c:` or `async with httpx.AsyncClient(...) as c:`."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1d: no `local-whisperx` references in production code.
#
# Local WhisperX support was removed in May 2026 (the app orchestrates
# external Whisper endpoints — see SUBGEN epic). The 21 GB worker image
# became ~500 MB by dropping torch/whisperx. Anyone re-introducing the
# string `local-whisperx` (a backend value, a UI label, a code branch)
# is reopening the size + complexity surface that was deliberately closed.
#
# Migration tests are exempt: their fixtures reference the historical
# schema state where `whisper_model`/`whisper_device` columns existed.
# Historical `backend_profile` JSONB reads in `history.py` are also fine
# — they surface old audit-trail data, not new code paths.
# ─────────────────────────────────────────────────────────────────────────────

LOCAL_WHISPERX_LITERAL = re.compile(r"\blocal[\-_]whisperx\b", re.IGNORECASE)

# Files that may keep the historical reference (audit-trail, migration tests,
# the grep-invariant itself). Everywhere else: re-introducing the literal
# fails CI fast.
LOCAL_WHISPERX_ALLOWLIST = {
    BACKEND_APP / "api" / "history.py",                # historical fallback resolver
    BACKEND_APP / "models" / "orm.py",                 # comment about historical snapshot
    BACKEND_APP / "alembic" / "versions" / "0010_drop_local_whisperx.py",
    ROOT / "backend" / "tests" / "test_migration_0008.py",  # tests pre-0010 schema state
    ROOT / "backend" / "tests" / "test_migration_0009.py",
    ROOT / "backend" / "tests" / "test_automations_invariants.py",  # this file
}


def test_no_local_whisperx_in_production_code():
    """Re-introducing `local-whisperx` anywhere outside the historical
    allow-list re-opens a deliberately-closed code surface."""
    violations: list[str] = []
    scan_roots = [BACKEND_APP, ROOT / "frontend" / "src"]
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in str(path) or "/node_modules/" in str(path):
                continue
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if path in LOCAL_WHISPERX_ALLOWLIST:
                continue
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                # Allow the historical comment marker `// removed` or `# removed`
                # if a future cleanup PR wants to note the removal.
                if LOCAL_WHISPERX_LITERAL.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert violations == [], (
        "`local-whisperx` re-introduced (removed May 2026):\n"
        + "\n".join(violations)
        + "\nThe slim worker image deliberately ships without torch/whisperx. "
        "If you need to add a new local-inference backend, give it a different "
        "name and a new image tag — don't resurrect this one."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 2: no broad `except Exception:`
# ─────────────────────────────────────────────────────────────────────────────

AUTOMATIONS_PY_FILES = [
    BACKEND_APP / "services" / "trigger_executor.py",
    BACKEND_APP / "services" / "trigger_service.py",
    BACKEND_APP / "services" / "cron_scheduler.py",
    BACKEND_APP / "services" / "watcher.py",
    BACKEND_APP / "api" / "triggers.py",
    BACKEND_APP / "api" / "webhooks.py",
]

BROAD_EXCEPT_PATTERN = re.compile(r'except\s+Exception\s*[:\(]')


def test_no_broad_except_exception_in_automations():
    """Automations modules must use narrow except clauses."""
    violations = []
    for path in AUTOMATIONS_PY_FILES:
        if not path.exists():
            continue
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), 1):
            if BROAD_EXCEPT_PATTERN.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert violations == [], (
        f"Broad `except Exception` found in automations code:\n"
        + "\n".join(violations)
        + "\nUse narrow exception classes (e.g. DBAPIError, ValueError, OSError)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 3: no window.X in new automations frontend code
# ─────────────────────────────────────────────────────────────────────────────

WINDOW_PATTERN = re.compile(r'\bwindow\.')


def _ts_files_in(*dirs: Path):
    for d in dirs:
        if d.exists():
            yield from d.glob("*.tsx")
            yield from d.glob("*.ts")


def test_no_window_x_in_automations_frontend():
    """Frontend automations code must use globalThis, not window."""
    violations = []
    for path in _ts_files_in(FRONTEND_AUTOMATIONS, FRONTEND_PAGE_AUTOMATIONS):
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), 1):
            # Skip comment lines
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if WINDOW_PATTERN.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert violations == [], (
        f"window.X usage found in automations frontend code:\n"
        + "\n".join(violations)
        + "\nUse `globalThis.X` instead (works in SSR/test environments too)."
    )
