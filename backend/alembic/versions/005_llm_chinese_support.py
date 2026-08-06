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
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.Text, nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="4096"),
        sa.Column("temperature", sa.Float, nullable=False, server_default="0.1"),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="60"),
        sa.Column("cost_per_1k_input", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("cost_per_1k_output", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("extra_headers", sa.Text, nullable=True),
        sa.Column("extra_body", sa.Text, nullable=True),
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

    # LLM feature toggles (global / per-repo)
    op.create_table(
        "llm_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enable_index_chinese_enrich", sa.Integer, nullable=False, server_default="1"),
        sa.Column("enable_query_llm_expand", sa.Integer, nullable=False, server_default="1"),
        sa.Column("enable_flow_label", sa.Integer, nullable=False, server_default="1"),
        sa.Column("default_provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_provider_id"], ["llm_providers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "repo_id", name="uix_llm_setting_scope_repo"),
    )
    op.create_index("idx_llm_setting_repo", "llm_settings", ["repo_id"])

    # Embedding Chinese enrichments
    op.create_table(
        "embedding_enrichments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chinese_summary", sa.Text, nullable=True),
        sa.Column("keywords", sa.Text, nullable=True),
        sa.Column("vertical_layer", sa.String(64), nullable=True),
        sa.Column("horizontal_module", sa.String(128), nullable=True),
        sa.Column("synonyms", sa.Text, nullable=True),
        sa.Column("generated_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["embedding_id"], ["embeddings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="SET NULL"),
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
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="1"),
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
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("layer", sa.String(64), nullable=True),
        sa.Column("module", sa.String(128), nullable=True),
        sa.Column("chinese_name", sa.String(256), nullable=True),
        sa.Column("io_description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", name="uix_symbol_flow_label_symbol"),
    )

    # Extend existing search_history with LLM-related fields
    op.add_column(
        "search_history",
        sa.Column("llm_provider_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "search_history",
        sa.Column("llm_input_tokens", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "search_history",
        sa.Column("llm_output_tokens", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_search_history_llm_provider",
        "search_history",
        "llm_providers",
        ["llm_provider_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_search_history_llm_provider", "search_history", type_="foreignkey")
    op.drop_column("search_history", "llm_output_tokens")
    op.drop_column("search_history", "llm_input_tokens")
    op.drop_column("search_history", "llm_provider_id")
    op.drop_index("idx_llm_setting_repo", table_name="llm_settings")
    op.drop_table("llm_settings")
    op.drop_table("symbol_flow_labels")
    op.drop_index("idx_domain_synonym_repo", table_name="domain_synonyms")
    op.drop_table("domain_synonyms")
    op.drop_table("embedding_enrichments")
    op.drop_table("llm_usage_logs")
    op.drop_index("idx_llm_provider_priority", table_name="llm_providers")
    op.drop_table("llm_providers")
