from celery import Celery
from celery.schedules import crontab

from app.core.config import app_settings

celery_app = Celery(
    "subtitles_worker",
    broker=app_settings.celery_broker_url,
    backend=app_settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Redis' default visibility_timeout is 3600s (1h). With acks_late=True a task
    # that runs longer than it is assumed-dead by the broker and RE-DELIVERED —
    # which silently restarted feature-length movie jobs from audio extraction
    # around the ~1h mark (mid cue-by-cue translation; prod incident 2026-06-20).
    # Set it far above the longest plausible job (a full movie translated locally
    # can run several hours). Genuine worker crashes are still recovered promptly
    # by orphan_recovery's worker_ready sweep on boot — NOT by this timeout — so
    # a large value costs nothing on the crash path.
    broker_transport_options={"visibility_timeout": 86400},  # 24h
    # Respawn the worker child after every task. Long-running pipeline
    # tasks accumulate per-process state (open NFS handles, HTTP client
    # pools, ffmpeg subprocess remnants) — on 2026-05-29, 9 consecutive
    # Landman episodes failed with "ffmpeg: No such file or directory"
    # on NFS paths that worked from a fresh worker. Restarting the child
    # per task makes any leak class structurally impossible. Cost: a
    # sub-second fork — negligible for tasks that take 5–30 min, and
    # the remote-API transcription backend means no whisperx reload cost.
    worker_max_tasks_per_child=1,
    # Import tasks at worker startup so the @celery_app.task decorators run
    # and the names are registered. Without this, the worker accepts the
    # message from Redis and raises KeyError("generate_subtitles") because
    # the task name isn't in its strategy table.
    #
    # `orphan_recovery` registers a `worker_ready` signal handler that sweeps
    # jobs left in `processing` by a SIGKILLed previous worker and
    # re-dispatches them — the listed import here is what triggers that
    # handler registration on worker boot. See orphan_recovery.py for why.
    imports=(
        "app.worker.tasks",
        "app.worker.orphan_recovery",
        "app.services.cron_scheduler",
    ),
    beat_schedule={
        "evaluate-cron-triggers-every-minute": {
            "task": "evaluate_cron_triggers",
            "schedule": crontab(minute="*"),
        },
    },
)
