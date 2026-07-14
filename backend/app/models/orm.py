import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    # One ACTIVE job per file, enforced by the database: watcher, cron,
    # webhook, and manual submissions racing on the same path collapse to a
    # single queued/processing row (2026-07 audit R2). Terminal rows do not
    # participate, so history keeps every run.
    __table_args__ = (
        Index(
            "uq_jobs_active_file",
            "file_path",
            unique=True,
            postgresql_where=text("status IN ('queued', 'processing')"),
            sqlite_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    phase: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    source_language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_size: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    log_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # SP-2: enqueue-time deep copy of the chosen Settings.profiles entry
    # (backend fields). The worker reads job config from here, never from
    # global Settings, so a later profile edit/delete can't corrupt a
    # queued job. (Local-WhisperX-era jobs also carried whisper_model and
    # whisper_device here; harmless leftover keys on historical rows.)
    backend_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # SP-3: per-job translation usage. tokens null when no translation ran;
    # cost_usd null = "n/a" (provider doesn't report cost), 0.0 = free
    # (local Ollama). Provider-reported only — not a maintained estimate.
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    jellyfin_refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Subtitle verification (post-completion, best-effort)
    verification_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verification_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verification_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    nas_mount_path: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default="/media"
    )
    jellyfin_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    jellyfin_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transcription_backend: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transcription_api_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transcription_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transcription_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    translation_api_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hf_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Named snapshots of the AI-backend configuration.
    # Each entry: ``{"name": str, "transcription_backend": ..., "translation_provider": ..., ...}``.
    profiles: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class Trigger(Base):
    __tablename__ = "triggers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    file_filter: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    webhook_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Stamped on every cron fire (even empty scans) so evaluation never
    # depends on a TriggerEvent row existing — see cron_scheduler.
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class TriggerEvent(Base):
    __tablename__ = "trigger_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    trigger_id: Mapped[str] = mapped_column(
        String, ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    matched_rule_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
