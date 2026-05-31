"""job model v2 - add missing columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('translation_provider', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('translation_model', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('error_message', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('source', sa.String(), nullable=False, server_default='manual'))


def downgrade() -> None:
    op.drop_column('jobs', 'source')
    op.drop_column('jobs', 'error_message')
    op.drop_column('jobs', 'translation_model')
    op.drop_column('jobs', 'translation_provider')
