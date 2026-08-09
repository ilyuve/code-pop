"""Pydantic request / response schemas."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _format_datetime(dt: datetime) -> str:
    """Serialize naive UTC datetimes with explicit +00:00 offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class RepoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    git_url: Optional[str] = None
    path: Optional[str] = None
    active_branches: Optional[List[str]] = Field(default=None, description="业务分支列表，最多 2 个；为空时只索引 default_branch")
    sync_mode: str = "auto"
    auto_sync: bool = False
    auto_sync_interval: int = 5


class RepoResponse(BaseModel):
    id: UUID
    name: str
    git_url: str
    description: Optional[str] = None
    local_path: str
    status: str
    error_message: Optional[str] = None
    last_indexed_at: Optional[datetime]
    default_branch: str = "main"
    active_branches: Optional[List[str]] = None
    sync_mode: str = "auto"
    auto_sync: bool = False
    auto_sync_interval: int = 5
    created_at: datetime
    updated_at: datetime
    total_files: int = 0
    indexed_files: int = 0
    symbol_count: int = 0

    @field_validator("active_branches", mode="before")
    @classmethod
    def _parse_active_branches(cls, value):
        if isinstance(value, str):
            try:
                return json.loads(value) if value.strip() else None
            except Exception:
                return None
        return value

    class Config:
        from_attributes = True
        json_encoders = {datetime: _format_datetime}


class RepoUpdate(BaseModel):
    active_branches: Optional[List[str]] = Field(default=None, description="业务分支列表，最多 2 个；传空列表可清空业务分支")
    sync_mode: Optional[str] = None
    auto_sync: Optional[bool] = None
    auto_sync_interval: Optional[int] = Field(default=None, description="定时轮询间隔（分钟），仅支持 5 / 15 / 30 / 60")


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
    branch: str = "main"
    limit: int = Field(default=20, ge=1, le=100)
    mode: str = "hybrid"


class SearchMeta(BaseModel):
    requested_branch: str
    actual_branch: str
    branch_fallback: bool = False


class SearchResultItem(BaseModel):
    id: UUID
    file_id: UUID
    repo_id: UUID
    repo_name: str
    file_path: str
    language: str
    content: str
    line: int
    score: float
    score_breakdown: dict
    file_role: str = "other"
    branch: str = "main"
    is_override: bool = False


class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    meta: SearchMeta


class SymbolSearchQuery(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
    branch: str = "main"
    limit: int = Field(default=20, ge=1, le=100)


class SymbolResponse(BaseModel):
    id: UUID
    file_id: UUID
    repo_id: UUID
    name: str
    type: str
    kind: str
    line: int
    column: int
    end_line: int
    is_exported: bool
    file_path: str

    class Config:
        from_attributes = True


class SearchHistoryResponse(BaseModel):
    id: UUID
    query: str
    repo_id: Optional[UUID]
    mode: str
    results_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: _format_datetime}


class BenchmarkCreate(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
    branch: str = "main"
    mode: str = "with_codepop"
    expected_files: List[str] = Field(default_factory=list)
    expected_lines: List[int] = Field(default_factory=list)


class BenchmarkResponse(BaseModel):
    id: UUID
    query: str
    repo_id: Optional[UUID]
    branch: str = "main"
    mode: str
    latency_ms: int
    results_count: int
    relevant_results_count: int
    token_consumed: int
    accuracy_score: float
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: _format_datetime}


class BenchmarkSummary(BaseModel):
    total_runs: int
    avg_latency_ms: float
    avg_token_consumed: float
    avg_accuracy_score: float
    latency_trend: List[Dict[str, Any]]
    savings_vs_baseline: Dict[str, float]


class SearchHistoryStats(BaseModel):
    total_queries: int
    avg_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_tokens_saved: int


class SearchHistoryDailyStats(BaseModel):
    date: str
    total_queries: int
    total_input_tokens: int
    total_output_tokens: int
    total_results_count: int


class SearchHistoryRecentItem(BaseModel):
    id: UUID
    query: str
    repo_id: Optional[UUID]
    repo_name: Optional[str] = None
    mode: str
    results_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: _format_datetime}


class WebhookPayload(BaseModel):
    ref: Optional[str] = None
    repository: Optional[dict] = None
    commits: Optional[List[dict]] = None


class WSMessage(BaseModel):
    type: str
    repo_id: Optional[str] = None
    progress: Optional[float] = None
    status: Optional[str] = None
    error: Optional[str] = None


class SymbolEntry(BaseModel):
    id: str
    name: str
    type: str
    file_path: str
    line: int
    relevance_score: float = 0.0
    layer: Optional[str] = None
    module: Optional[str] = None
    chinese_name: Optional[str] = None
    io_description: Optional[str] = None


class CallChain(BaseModel):
    root: SymbolEntry
    upstream: List[SymbolEntry] = []
    downstream: List[SymbolEntry] = []
    depth: int = 0
    flow_summary: Optional[str] = None


class FileRole(str):
    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    MODEL = "model"
    CONFIG = "config"
    MIDDLEWARE = "middleware"
    UTILITY = "utility"
    TEST = "test"
    OTHER = "other"


class FileSummary(BaseModel):
    path: str
    role: str = "other"
    relevance_score: float = 0.0
    key_symbols: List[str] = []


class CodeContext(BaseModel):
    query: str
    query_intent: str
    branch: str = "main"
    matched_concepts: List[str] = []
    entry_points: List[SymbolEntry] = []
    call_chain: Optional[CallChain] = None
    flow_summary: Optional[str] = None
    related_files: List[FileSummary] = []
    code_snippets: List[SearchResultItem] = []
    total_files: int = 0
    total_symbols: int = 0
    search_latency_ms: int = 0
    meta: Optional[SearchMeta] = None


class DebugPathOverrides(BaseModel):
    enabled: Optional[List[str]] = Field(
        default=None,
        description="Paths to run; defaults to all five paths when omitted.",
    )
    top_k: Optional[Dict[str, int]] = Field(
        default=None,
        description="Per-path top_k overrides, e.g. {'vector': 30}.",
    )


class DebugSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: UUID
    branch: str = "main"
    limit: int = Field(default=20, ge=1, le=100)
    path_overrides: Optional[DebugPathOverrides] = None
    enable_llm_expand: bool = False


class DebugPathSnapshot(BaseModel):
    name: str
    enabled: bool
    top_k: int
    latency_ms: int
    hit_count: int
    hits: List[Dict[str, Any]]


class DebugFusionSnapshot(BaseModel):
    rrf_k: int
    hit_count: int
    hits: List[Dict[str, Any]]


class DebugRerankStage(BaseModel):
    input_count: int
    output_count: int
    output: List[Dict[str, Any]]


class DebugRerankSnapshot(BaseModel):
    code_reranker: DebugRerankStage
    m3_reranker: DebugRerankStage


class DebugSearchResponse(BaseModel):
    query_analysis: Dict[str, Any]
    paths: List[DebugPathSnapshot]
    fusion: DebugFusionSnapshot
    rerank: DebugRerankSnapshot
    final_context: CodeContext
    total_latency_ms: int


class CodeContextResponse(BaseModel):
    context: Optional[CodeContext] = None
    success: bool = True
    error: Optional[str] = None


class RouteSearchRequest(BaseModel):
    path_pattern: Optional[str] = None
    handler_name: Optional[str] = None
    http_method: Optional[str] = None
    repo_id: str
    branch: str = "main"


class RouteResponse(BaseModel):
    framework: str
    method: str
    path: str
    handler: str
    file_path: str
    line: int


class ImpactRequest(BaseModel):
    symbol_name: str
    repo_id: Optional[str] = None
    branch: str = "main"


class ImpactResponse(BaseModel):
    symbol: str
    file_path: str
    line: int
    affected_routes: List[Dict]
    upstream_chain: List[str]
    depth: int
    risk_level: str
