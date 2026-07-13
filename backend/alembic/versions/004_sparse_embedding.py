"""Create sparse_embeddings table.

Revision ID: 004
Revises: 003
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sparse_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", sa.Integer, nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.ForeignKeyConstraint(["embedding_id"], ["embeddings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sparse_embedding_token", "sparse_embeddings", ["embedding_id", "token_id"])
    op.create_index("idx_sparse_token_weight", "sparse_embeddings", ["token_id", "weight"])


def downgrade() -> None:
    op.drop_index("idx_sparse_token_weight", table_name="sparse_embeddings")
    op.drop_index("idx_sparse_embedding_token", table_name="sparse_embeddings")
    op.drop_table("sparse_embeddings")
