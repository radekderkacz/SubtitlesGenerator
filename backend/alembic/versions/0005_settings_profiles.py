"""add profiles JSON column to settings

Stores named snapshots of the AI-backend configuration so the user can
flip between e.g. "Homelab Local" (LXC + Ollama qwen) and "OpenAI Paid"
(remote OpenAI Whisper + GPT-4o) without retyping URLs/keys each time.

Profiles live as a JSON array on the singleton Settings row — there is
only one user / household, so a separate table would be overkill. Each
profile entry is a dict with at minimum a `name` plus the transcription/
translation field set; the application layer handles validation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-11 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'settings',
        sa.Column('profiles', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('settings', 'profiles')
