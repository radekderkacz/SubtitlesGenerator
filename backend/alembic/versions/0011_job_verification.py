"""Add subtitle-verification columns to job.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("verification_status", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("verification_score", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("verification_report", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("verified_at", "verification_report", "verification_score", "verification_status"):
        op.drop_column("jobs", col)
