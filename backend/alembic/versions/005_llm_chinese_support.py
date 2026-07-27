"""Add LLM provider, Chinese enrichment, domain synonyms and symbol flow labels.

Revision ID: 005
Revises: 004
Create Date: 2026-07-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # LLM providers
    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.Text, nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="4096"),
        sa.Column("temperature", sa.Float, nullable=False, server_default="0.1"),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="60"),
        sa.Column("extra_headers", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_llm_provider_priority", "llm_providers", ["priority", "enabled"])

    # LLM usage logs
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Embedding Chinese enrichments
    op.create_table(
        "embedding_enrichments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chinese_summary", sa.Text, nullable=True),
        sa.Column("keywords", sa.Text, nullable=True),
        sa.Column("vertical_layer", sa.String(64), nullable=True),
        sa.Column("horizontal_module", sa.String(128), nullable=True),
        sa.Column("synonyms", sa.Text, nullable=True),
        sa.Column("generated_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["embedding_id"], ["embeddings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("embedding_id"),
    )

    # Domain-specific synonyms
    op.create_table(
        "domain_synonyms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_term", sa.String(128), nullable=False),
        sa.Column("synonyms", sa.Text, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="auto"),
        sa.Column("frequency", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "canonical_term", name="uix_domain_synonym_repo_term"),
    )
    op.create_index("idx_domain_synonym_repo", "domain_synonyms", ["repo_id"])

    # Symbol flow labels
    op.create_table(
        "symbol_flow_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer", sa.String(64), nullable=True),
        sa.Column("module", sa.String(128), nullable=True),
        sa.Column("chinese_name", sa.String(256), nullable=True),
        sa.Column("io_description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", name="uix_symbol_flow_label_symbol"),
    )


def downgrade() -> None:
    op.drop_table("symbol_flow_labels")
    op.drop_index("idx_domain_synonym_repo", table_name="domain_synonyms")
    op.drop_table("domain_synonyms")
    op.drop_table("embedding_enrichments")
    op.drop_table("llm_usage_logs")
    op.drop_index("idx_llm_provider_priority", table_name="llm_providers")
    op.drop_table("llm_providers")
