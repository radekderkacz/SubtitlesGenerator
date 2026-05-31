"""Drop local-WhisperX support: scrub backend setting + delete columns.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-29

The app no longer ships a local-inference path. Existing Settings rows
configured for `local-whisperx` are converted to `NULL` (forcing the user
to reconfigure as remote-api in the UI). The two now-dead columns
`whisper_model` and `whisper_device` are dropped. Profiles JSONB is
scrubbed in case any saved profile carried the legacy backend value.

Historical `job.backend_profile` snapshots are left alone — they're an
audit trail, and `history.py` still reads `whisper_model` from there as
a fallback so old rows continue to render correctly.
"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE settings SET transcription_backend = NULL "
        "WHERE transcription_backend = 'local-whisperx'"
    )
    # `profiles` is stored as `json` (not jsonb), so cast for the elementwise
    # transform. Strip the 'local-whisperx' transcription_backend key from
    # each profile dict; leave other keys untouched.
    op.execute("""
        UPDATE settings
        SET profiles = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem->>'transcription_backend' = 'local-whisperx'
                    THEN elem - 'transcription_backend'
                    ELSE elem
                END
            )::json
            FROM jsonb_array_elements(profiles::jsonb) AS elem
        )
        WHERE profiles IS NOT NULL
          AND json_typeof(profiles) = 'array'
    """)
    op.drop_column("settings", "whisper_model")
    op.drop_column("settings", "whisper_device")


def downgrade() -> None:
    # Re-add the columns (data loss is one-way — no attempt to restore).
    op.add_column(
        "settings",
        sa.Column("whisper_model", sa.String(), nullable=False, server_default="large-v3"),
    )
    op.add_column(
        "settings",
        sa.Column("whisper_device", sa.String(), nullable=True, server_default="auto"),
    )
