"""Create framework_routes table.

Revision ID: 003
Revises: 002
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "framework_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework", sa.String(32), nullable=False),
        sa.Column("http_method", sa.String(16), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("handler_symbol", sa.Text, nullable=False),
        sa.Column("line_number", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["code_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_routes_repo_path", "framework_routes", ["repo_id", "path"])
    op.create_index("idx_routes_handler", "framework_routes", ["repo_id", "handler_symbol"])


def downgrade() -> None:
    op.drop_index("idx_routes_handler", table_name="framework_routes")
    op.drop_index("idx_routes_repo_path", table_name="framework_routes")
    op.drop_table("framework_routes")