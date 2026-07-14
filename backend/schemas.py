"""Pydantic request / response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RepoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    git_url: Optional[str] = None
    path: Optional[str] = None


class RepoResponse(BaseModel):
    id: UUID
    name: str
    git_url: str
    local_path: str
    status: str
    error_message: Optional[str] = None
    last_indexed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    total_files: int = 0
    indexed_files: int = 0

    class Config:
        from_attributes = True


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
    limit: int = Field(default=20, ge=1, le=100)
    mode: str = "hybrid"


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


class SymbolSearchQuery(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
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


class BenchmarkCreate(BaseModel):
    query: str = Field(..., min_length=1)
    repo_id: Optional[UUID] = None
    mode: str = "with_codepop"
    expected_files: List[str] = Field(default_factory=list)
    expected_lines: List[int] = Field(default_factory=list)


class BenchmarkResponse(BaseModel):
    id: UUID
    query: str
    repo_id: Optional[UUID]
    mode: str
    latency_ms: int
    results_count: int
    relevant_results_count: int
    token_consumed: int
    accuracy_score: float
    created_at: datetime

    class Config:
        from_attributes = True


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


class CallChain(BaseModel):
    root: SymbolEntry
    upstream: List[SymbolEntry] = []
    downstream: List[SymbolEntry] = []
    depth: int = 0


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
    matched_concepts: List[str] = []
    entry_points: List[SymbolEntry] = []
    call_chain: Optional[CallChain] = None
    related_files: List[FileSummary] = []
    code_snippets: List[SearchResultItem] = []
    total_files: int = 0
    total_symbols: int = 0
    search_latency_ms: int = 0
    degraded: bool = False
    degradation_reason: Optional[str] = None
    unavailable_sources: List[str] = []


class CodeContextResponse(BaseModel):
    context: Optional[CodeContext] = None
    success: bool = True
    error: Optional[str] = None


class RouteSearchRequest(BaseModel):
    path_pattern: Optional[str] = None
    handler_name: Optional[str] = None
    http_method: Optional[str] = None
    repo_id: str


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


class ImpactResponse(BaseModel):
    symbol: str
    file_path: str
    line: int
    affected_routes: List[Dict]
    upstream_chain: List[str]
    depth: int
    risk_level: str
