"""SQLAlchemy ORM models for the CodePop backend."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from config import settings
from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class RepoStatus(str, PyEnum):
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    error = "error"


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    git_url = Column(String(512), nullable=True)
    local_path = Column(String(512), nullable=False)
    status = Column(String(32), default=RepoStatus.pending.value, nullable=False)
    error_message = Column(Text, nullable=True)
    last_indexed_at = Column(DateTime, nullable=True)
    indexing_heartbeat_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    files = relationship("CodeFile", back_populates="repo", cascade="all, delete-orphan")
    symbols = relationship("Symbol", back_populates="repo", cascade="all, delete-orphan")
    embeddings = relationship("Embedding", back_populates="repo", cascade="all, delete-orphan")
    edges = relationship("CallGraphEdge", back_populates="repo", cascade="all, delete-orphan")
    history = relationship("SearchHistory", back_populates="repo", cascade="all, delete-orphan")


class CodeFile(Base):
    __tablename__ = "code_files"
    __table_args__ = (UniqueConstraint("repo_id", "path", name="uix_file_repo_path"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    path = Column(String(1024), nullable=False)
    language = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    repo = relationship("Repository", back_populates="files")
    symbols = relationship("Symbol", back_populates="file", cascade="all, delete-orphan")
    embeddings = relationship("Embedding", back_populates="file", cascade="all, delete-orphan")


class Symbol(Base):
    __tablename__ = "symbols"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(512), nullable=False)
    type = Column(String(32), nullable=False)  # function / class / interface / variable
    kind = Column(String(32), nullable=False)
    line = Column(Integer, nullable=False)
    column = Column(Integer, default=0, nullable=False)
    end_line = Column(Integer, nullable=False)
    end_column = Column(Integer, default=0, nullable=False)
    is_exported = Column(Integer, default=0, nullable=False)  # 0/1

    file = relationship("CodeFile", back_populates="symbols")
    repo = relationship("Repository", back_populates="symbols")


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.embedding_dim), nullable=False)
    token_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    file = relationship("CodeFile", back_populates="embeddings")
    repo = relationship("Repository", back_populates="embeddings")


class SparseEmbedding(Base):
    __tablename__ = "sparse_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    embedding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("embeddings.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_id = Column(Integer, nullable=False)
    weight = Column(Float, nullable=False)

    __table_args__ = (
        Index("idx_sparse_embedding_token", "embedding_id", "token_id"),
        Index("idx_sparse_token_weight", "token_id", "weight"),
    )


class CallGraphEdge(Base):
    __tablename__ = "call_graph_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_symbol_id = Column(UUID(as_uuid=True), ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False)
    target_symbol_id = Column(UUID(as_uuid=True), ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    call_type = Column(String(32), default="direct", nullable=False)

    repo = relationship("Repository", back_populates="edges")


class SearchHistory(Base):
    __tablename__ = "search_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    mode = Column(String(32), default="hybrid", nullable=False)
    results_count = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Integer, default=0, nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    llm_provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    llm_input_tokens = Column(Integer, default=0, nullable=False)
    llm_output_tokens = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    repo = relationship("Repository", back_populates="history")
    llm_provider = relationship("LlmProvider")


class BenchmarkMode(str, PyEnum):
    with_codepop = "with_codepop"
    without_codepop = "without_codepop"


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    mode = Column(String(32), default=BenchmarkMode.with_codepop.value, nullable=False)
    latency_ms = Column(Integer, default=0, nullable=False)
    results_count = Column(Integer, default=0, nullable=False)
    relevant_results_count = Column(Integer, default=0, nullable=False)
    token_consumed = Column(Integer, default=0, nullable=False)
    accuracy_score = Column(Integer, default=0, nullable=False)  # 0-100 scaled integer
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    repo = relationship("Repository")


class IndexingProgress(Base):
    __tablename__ = "indexing_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(32), nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    current = Column(Integer, default=0, nullable=False)
    total = Column(Integer, default=0, nullable=False)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("repo_id", "stage", name="uix_repo_stage"),
    )


class IndexingLog(Base):
    __tablename__ = "indexing_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    level = Column(String(16), default="info", nullable=False)
    stage = Column(String(32), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FrameworkRoute(Base):
    __tablename__ = "framework_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("code_files.id", ondelete="CASCADE"),
        nullable=False,
    )

    framework = Column(String(32), nullable=False)
    http_method = Column(String(16), nullable=False)
    path = Column(Text, nullable=False)
    handler_symbol = Column(Text, nullable=False)
    line_number = Column(Integer, nullable=False)

    __table_args__ = (
        Index("idx_routes_repo_path", "repo_id", "path"),
        Index("idx_routes_handler", "repo_id", "handler_symbol"),
    )

    repo = relationship("Repository")
    file = relationship("CodeFile")


class LlmProviderCapability(str, PyEnum):
    chat = "chat"
    embed = "embed"
    both = "both"


class LlmProviderType(str, PyEnum):
    openai_compatible = "openai_compatible"
    deepseek = "deepseek"
    glm = "glm"
    azure = "azure"
    custom = "custom"


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    provider_type = Column(
        String(32),
        default=LlmProviderType.openai_compatible.value,
        nullable=False,
    )
    base_url = Column(String(512), nullable=False)
    api_key = Column(Text, nullable=False)  # encrypted
    model = Column(String(128), nullable=False)
    capability = Column(String(32), default=LlmProviderCapability.chat.value, nullable=False)
    priority = Column(Integer, default=0, nullable=False)
    enabled = Column(Integer, default=1, nullable=False)  # 0/1
    max_tokens = Column(Integer, default=4096, nullable=False)
    temperature = Column(Float, default=0.1, nullable=False)
    timeout_seconds = Column(Integer, default=60, nullable=False)
    cost_per_1k_input = Column(Numeric(10, 6), default=0, nullable=False)
    cost_per_1k_output = Column(Numeric(10, 6), default=0, nullable=False)
    extra_headers = Column(Text, nullable=True)  # JSON
    extra_body = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_llm_provider_priority", "priority", "enabled"),
    )


class LlmUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True)
    operation = Column(String(64), nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="success", nullable=False)  # success / error / degraded
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    provider = relationship("LlmProvider")


class LlmSetting(Base):
    __tablename__ = "llm_settings"
    __table_args__ = (
        UniqueConstraint("scope", "repo_id", name="uix_llm_setting_scope_repo"),
        Index("idx_llm_setting_repo", "repo_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(32), nullable=False)  # global / repo
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True)
    enable_index_chinese_enrich = Column(Integer, default=1, nullable=False)  # 0/1
    enable_query_llm_expand = Column(Integer, default=1, nullable=False)  # 0/1
    enable_flow_label = Column(Integer, default=1, nullable=False)  # 0/1
    default_provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    repo = relationship("Repository")
    default_provider = relationship("LlmProvider")


class EmbeddingEnrichment(Base):
    __tablename__ = "embedding_enrichments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    embedding_id = Column(UUID(as_uuid=True), ForeignKey("embeddings.id", ondelete="CASCADE"), nullable=False, unique=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    content_hash = Column(String(64), nullable=False)
    chinese_summary = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)  # JSON list
    vertical_layer = Column(String(64), nullable=True)
    horizontal_module = Column(String(128), nullable=True)
    synonyms = Column(Text, nullable=True)  # JSON dict
    generated_by = Column(String(128), nullable=True)  # model name
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    embedding = relationship("Embedding", back_populates="enrichment")
    provider = relationship("LlmProvider")


class DomainSynonym(Base):
    __tablename__ = "domain_synonyms"
    __table_args__ = (
        UniqueConstraint("repo_id", "canonical_term", name="uix_domain_synonym_repo_term"),
        Index("idx_domain_synonym_repo", "repo_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    canonical_term = Column(String(128), nullable=False)
    synonyms = Column(Text, nullable=False)  # JSON list
    source = Column(String(32), default="auto", nullable=False)  # auto / manual
    hit_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SymbolFlowLabel(Base):
    __tablename__ = "symbol_flow_labels"
    __table_args__ = (
        UniqueConstraint("symbol_id", name="uix_symbol_flow_label_symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol_id = Column(UUID(as_uuid=True), ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    layer = Column(String(64), nullable=True)  # controller / service / repository / etc.
    module = Column(String(128), nullable=True)
    chinese_name = Column(String(256), nullable=True)
    io_description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    symbol = relationship("Symbol", back_populates="flow_label")
    provider = relationship("LlmProvider")


# Wire up reverse relationships
Embedding.enrichment = relationship("EmbeddingEnrichment", back_populates="embedding", uselist=False, cascade="all, delete-orphan")
Symbol.flow_label = relationship("SymbolFlowLabel", back_populates="symbol", uselist=False)
Repository.llm_usage_logs = relationship("LlmUsageLog", back_populates="repo")
Repository.domain_synonyms = relationship("DomainSynonym", back_populates="repo", cascade="all, delete-orphan")
LlmUsageLog.repo = relationship("Repository", back_populates="llm_usage_logs")
DomainSynonym.repo = relationship("Repository", back_populates="domain_synonyms")
