"""job usage + cost columns

Stores per-job translation token counts and USD cost reported by the
LiteLLM provider. Columns are nullable: null tokens means no translation
ran; null cost_usd means the provider did not report a cost (not zero).

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    for c in ("cost_usd", "total_tokens", "completion_tokens", "prompt_tokens"):
        op.drop_column("jobs", c)
