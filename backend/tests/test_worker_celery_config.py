"""Pins critical Celery worker configuration that protects production
from long-running-process pathologies.

The 2026-05-29 incident: 9 consecutive Landman episodes failed with
"ffmpeg: No such file or directory" on NFS paths that worked from a
fresh worker. Root cause was a long-running-process state leak (open
file handles, HTTP pool, subprocess remnants — pinned-down candidate
unknown). The fix is `worker_max_tasks_per_child=1`: respawn the
child after every task. Whoever drops it without replacing it with
an equivalent guarantee re-opens the bug class.
"""
from app.worker.celery_app import celery_app


def test_worker_concurrency_is_one():
    """Single-process worker — orphan_recovery + DB session assumptions
    depend on this."""
    assert celery_app.conf.worker_concurrency == 1


def test_worker_max_tasks_per_child_is_one():
    """Worker child respawns per task. Drops in-process state that has
    historically caused ffmpeg-on-NFS to fail with ENOENT on tasks 2..N.
    If a future change ever wants to relax this, the replacement MUST
    audit every long-lived resource in worker.tasks for leak safety AND
    add an integration test that runs generate_subtitles ≥10 times on
    the same child and asserts no failures."""
    assert celery_app.conf.worker_max_tasks_per_child == 1


def test_worker_prefetch_multiplier_is_one():
    """One reserved task at a time so concurrency=1 actually serializes."""
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_task_acks_late_is_true():
    """If the worker crashes mid-task, the broker re-delivers (acks_late).
    Combined with orphan_recovery on boot, jobs aren't silently lost."""
    assert celery_app.conf.task_acks_late is True


def test_visibility_timeout_far_exceeds_default_for_long_jobs():
    """Redis' default visibility_timeout is 3600s (1h). With acks_late=True,
    any task running longer than it is assumed-dead and RE-DELIVERED — which
    restarted feature-length movie jobs from audio extraction mid-translation
    (prod incident 2026-06-20). Must be set far above the longest plausible
    job; genuine crashes are recovered by orphan_recovery on boot, not by this
    timeout. If a future change lowers this below a few hours, long jobs break."""
    vt = celery_app.conf.broker_transport_options.get("visibility_timeout")
    assert vt is not None and vt >= 86400, (
        f"visibility_timeout must be >= 86400s (got {vt}) — long jobs get "
        "re-delivered and restarted at the 3600s default"
    )
