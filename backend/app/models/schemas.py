from datetime import datetime
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from croniter import croniter


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobPhase(str, Enum):
    extracting = "extracting"
    transcribing = "transcribing"
    translating = "translating"
    writing = "writing"
    done = "done"


class JobCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    file_path: str
    profile_name: str
    source_language: str = "auto"
    translate: bool = False
    target_language: Optional[str] = None
    source: Optional[str] = "manual"
    # None = follow the global settings.prefer_existing_subs toggle;
    # an explicit bool overrides it for this job only.
    use_existing_subs: Optional[bool] = None

    @model_validator(mode="after")
    def _validate(self) -> "JobCreate":
        if not self.profile_name.strip():
            raise ValueError("profile_name is required")
        if self.translate and (
            not self.target_language or self.target_language == "auto"
        ):
            raise ValueError(
                "Pick a specific target language when translation is enabled — "
                '"Auto-detect" is for source detection only.'
            )
        return self


class JobSubmitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: JobStatus
    created_at: datetime


class FileBrowseEntry(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime
    has_srt: bool


class FileBrowseResponse(BaseModel):
    path: str
    parent: Optional[str] = None
    directories: list[str]
    files: list[FileBrowseEntry]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    status: JobStatus
    phase: Optional[JobPhase] = None
    progress: int
    file_path: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    model_size: Optional[str] = None
    translation_provider: Optional[str] = None
    translation_model: Optional[str] = None
    log_path: Optional[str] = None
    error_message: Optional[str] = None
    source: str = "manual"
    source_srt_path: Optional[str] = None
    use_existing_subs: bool = True
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    jellyfin_refreshed_at: Optional[datetime] = None
    verification_status: Optional[str] = None
    verification_score: Optional[float] = None
    verification_report: Optional[dict] = None
    verified_at: Optional[datetime] = None


class JobUpdatePayload(BaseModel):
    """SSE ``job_update`` event payload shape (mirrors build_job_event_payload)."""

    id: str
    status: str
    phase: Optional[str] = None
    progress: int
    updated_at: str  # ISO-8601 string as emitted by job_events
    file_path: str
    error_message: Optional[str] = None
    verification_status: Optional[str] = None
    verification_score: Optional[float] = None
    verification_report: Optional[dict] = None
    verified_at: Optional[str] = None  # ISO-8601 string or None


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    status: JobStatus
    file_path: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    model_size: Optional[str] = None
    translation_provider: Optional[str] = None
    translation_model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    srt_path: Optional[str] = None
    # Set when the run started from an existing SRT (existing-subtitles gate
    # or fast re-translate retry) instead of transcribing from scratch.
    source_srt_path: Optional[str] = None
    error_message: Optional[str] = None
    verification_status: Optional[str] = None
    verification_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    jellyfin_refreshed_at: Optional[datetime] = None


class HistoryDeleteResponse(BaseModel):
    deleted: int


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    nas_mount_path: Optional[str] = None
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    transcription_api_url: Optional[str] = None
    transcription_model: Optional[str] = None
    transcription_api_key: Optional[str] = None
    translation_provider: Optional[str] = None
    translation_model: Optional[str] = None
    translation_api_key: Optional[str] = None
    translation_api_url: Optional[str] = None
    hf_token: Optional[str] = None
    # list of named AI-backend snapshots
    profiles: Optional[list] = None
    prefer_existing_subs: Optional[bool] = None


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    nas_mount_path: Optional[str] = None
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    transcription_api_url: Optional[str] = None
    transcription_model: Optional[str] = None
    transcription_api_key: Optional[str] = None
    translation_provider: Optional[str] = None
    translation_model: Optional[str] = None
    translation_api_key: Optional[str] = None
    translation_api_url: Optional[str] = None
    hf_token: Optional[str] = None
    # list of named AI-backend snapshots
    profiles: Optional[list] = None
    prefer_existing_subs: bool = True
    created_at: datetime
    updated_at: datetime


class TestTranscriptionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class TestJellyfinRequest(BaseModel):
    url: str
    api_key: str


class TestTranslationRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str  # "ollama", "openai", "google", "custom"
    url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class TestConnectivityResponse(BaseModel):
    ok: bool
    detail: str


class ListTranslationModelsRequest(BaseModel):
    provider: str  # "ollama", "openai", "google", "custom"
    url: Optional[str] = None
    api_key: Optional[str] = None


class ListTranslationModelsResponse(BaseModel):
    models: list[str]
    detail: Optional[str] = None


class TestTranslationModelRequest(BaseModel):
    """Body for ``POST /settings/test-translation-model`` — runs the same
    two probes that surfaced the gemma3-vs-aya quality gap on 2026-05-15
    (multi-sentence proper-noun preservation + glossary JSON-array
    compliance at long context). Distinct from ``TestTranslationRequest``
    above which only does a 1-token connectivity ping."""
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    target_language: str = "pl"  # Polish is the most-tested target


class TestTranslationModelResponse(BaseModel):
    ok: bool
    # null when the probe couldn't run (network error, etc) so the UI can
    # distinguish "probe failed to execute" from "probe ran but the model
    # failed the check".
    preserves_proper_nouns: Optional[bool] = None
    glossary_json_valid: Optional[bool] = None
    # Wall-clock seconds for the translation probe — a rough sec/cue
    # estimate for "could I finish a 1400-cue feature film in reasonable
    # time?" Multiplies by ~1400 in the UI.
    sec_per_segment: Optional[float] = None
    # The translated sample line; user can eyeball quality without running
    # a real job.
    sample_translation: Optional[str] = None
    # The proper nouns the model would emit if asked to extract — visible
    # so the user can see whether the glossary will be useful for their
    # content.
    sample_glossary: Optional[list[str]] = None
    detail: str


class TriggerType(str, Enum):
    watch = "watch"
    cron = "cron"
    webhook = "webhook"


class TriggerEventOutcome(str, Enum):
    submitted = "submitted"
    skipped_no_rule = "skipped_no_rule"
    skipped_existing_srt = "skipped_existing_srt"
    skipped_duplicate = "skipped_duplicate"
    skipped_scan_limit = "skipped_scan_limit"
    skipped_not_video = "skipped_not_video"
    failed_dispatch = "failed_dispatch"


class ActionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    profile_name: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    skip_if_srt: bool = True


class FileFilterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["all", "subfolder", "name_contains"] = "all"
    value: Optional[str] = None

    @model_validator(mode="after")
    def _value_required_unless_all(self):
        if self.type != "all" and not (self.value or "").strip():
            raise ValueError(f"file_filter type '{self.type}' requires a non-empty value")
        return self


def _require_time(t: Optional[str]) -> None:
    import re
    if not t or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
        raise ValueError("schedule needs time as HH:MM (24h)")


class ScheduleSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["hourly", "daily", "weekly", "monthly"]
    every_n_hours: Optional[int] = None      # hourly
    time: Optional[str] = None               # daily/weekly/monthly, "HH:MM"
    day_of_week: Optional[int] = None        # weekly, 0=Sun..6=Sat
    day_of_month: Optional[int] = None       # monthly, 1..28

    @model_validator(mode="after")
    def _validate_per_mode(self):
        if self.mode == "hourly":
            if self.every_n_hours not in (1, 2, 3, 4, 6, 8, 12):
                raise ValueError("hourly schedule needs every_n_hours in 1/2/3/4/6/8/12")
        elif self.mode == "daily":
            _require_time(self.time)
        elif self.mode == "weekly":
            _require_time(self.time)
            if self.day_of_week is None or not 0 <= self.day_of_week <= 6:
                raise ValueError("weekly schedule needs day_of_week 0..6")
        elif self.mode == "monthly":
            _require_time(self.time)
            if self.day_of_month is None or not 1 <= self.day_of_month <= 28:
                raise ValueError("monthly schedule needs day_of_month 1..28")
        return self


class WatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)


class CronConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_path: str = Field(min_length=1)
    schedule: ScheduleSchema
    cron: Optional[str] = None   # server-derived; present on responses, ignored on input


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_path: Optional[str] = None


TriggerConfig = Union[WatchConfig, CronConfig, WebhookConfig]


class TriggerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: TriggerType
    config: dict
    action: ActionSchema
    file_filter: FileFilterSchema = Field(default_factory=lambda: FileFilterSchema(type="all"))
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_config_per_type(self):
        if self.type == TriggerType.watch:
            WatchConfig.model_validate(self.config)
        elif self.type == TriggerType.cron:
            CronConfig.model_validate(self.config)
        elif self.type == TriggerType.webhook:
            WebhookConfig.model_validate(self.config)
        return self


class TriggerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    config: Optional[dict] = None
    action: Optional[ActionSchema] = None
    file_filter: Optional[FileFilterSchema] = None
    enabled: Optional[bool] = None


class TriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    type: TriggerType
    config: dict
    action: Optional[ActionSchema] = None
    file_filter: Optional[FileFilterSchema] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_fired_at: Optional[datetime] = None
    fire_count_24h: int = 0


class TriggerSecretResponse(BaseModel):
    webhook_secret: str


class TriggerEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    trigger_id: str
    fired_at: datetime
    event_payload: dict
    matched_rule_index: Optional[int] = None
    outcome: TriggerEventOutcome
    job_id: Optional[str] = None
    error_message: Optional[str] = None
