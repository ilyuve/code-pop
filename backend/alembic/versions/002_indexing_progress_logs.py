"""Create indexing_progress and indexing_logs tables.

Revision ID: 002_indexing_progress_logs
Revises: 001_bge_m3_1024
Create Date: 2026-07-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_indexing_progress_logs'
down_revision = '001_bge_m3_1024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'indexing_progress',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repo_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('current', sa.Integer(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repo_id', 'stage', name='uix_repo_stage'),
    )
    
    op.create_table(
        'indexing_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repo_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('indexing_logs')
    op.drop_table('indexing_progress')