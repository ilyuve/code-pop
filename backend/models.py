"""SQLAlchemy ORM models for the CodePop backend."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
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
    git_url = Column(String(512), nullable=False)
    local_path = Column(String(512), nullable=False)
    status = Column(String(32), default=RepoStatus.pending.value, nullable=False)
    last_indexed_at = Column(DateTime, nullable=True)
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    repo = relationship("Repository", back_populates="history")


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
