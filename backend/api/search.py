"""Search endpoints."""

import time
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from config import settings
from database import get_db
from models import SearchHistory
from schemas import (
    BenchmarkCreate,
    BenchmarkResponse,
    BenchmarkSummary,
    CodeContextResponse,
    SearchHistoryResponse,
    SearchHistoryStats,
    SearchQuery,
    SearchResultItem,
    SymbolSearchQuery,
)
from services.benchmark_service import BenchmarkService
from services.embedder import Embedder
from services.searcher import Searcher

router = APIRouter(prefix="/api/search", tags=["search"])
embedder = Embedder()


def _estimate_output_tokens(results: List[SearchResultItem]) -> int:
    """Estimate output tokens from result contents."""
    total_chars = sum(len(r.content) for r in results)
    return max(0, total_chars // 4)


def _record_history(
    db: Session,
    query: str,
    repo_id: Optional[UUID],
    mode: str,
    results_count: int,
    latency_ms: int,
    results: List[SearchResultItem],
) -> None:
    input_tokens = embedder.count_tokens(query)
    output_tokens = _estimate_output_tokens(results)
    history = SearchHistory(
        query=query,
        repo_id=repo_id,
        mode=mode,
        results_count=results_count,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(history)
    db.commit()


@router.post("", response_model=List[SearchResultItem])
def search(query: SearchQuery, db: Session = Depends(get_db)) -> List[SearchResultItem]:
    if query.limit > settings.search_max_limit:
        raise HTTPException(status_code=400, detail=f"limit exceeds {settings.search_max_limit}")

    start = time.perf_counter()
    searcher = Searcher(db)
    results = searcher.hybrid_search(query.query, query.repo_id, query.limit)
    latency_ms = int((time.perf_counter() - start) * 1000)

    _record_history(db, query.query, query.repo_id, query.mode, len(results), latency_ms, results)
    return results


@router.post("/symbol", response_model=List[SearchResultItem])
def symbol_search(
    query: SymbolSearchQuery, db: Session = Depends(get_db)
) -> List[SearchResultItem]:
    if query.limit > settings.search_max_limit:
        raise HTTPException(status_code=400, detail=f"limit exceeds {settings.search_max_limit}")

    start = time.perf_counter()
    searcher = Searcher(db)
    results = searcher.symbol_search(query.query, query.repo_id, query.limit)
    latency_ms = int((time.perf_counter() - start) * 1000)

    _record_history(db, query.query, query.repo_id, "symbol", len(results), latency_ms, results)
    return results


@router.post("/context", response_model=CodeContextResponse)
def search_context(
    query: SearchQuery,
    db: Session = Depends(get_db),
):
    if query.limit > settings.search_max_limit:
        raise HTTPException(status_code=400, detail=f"limit exceeds {settings.search_max_limit}")

    try:
        searcher = Searcher(db)
        context = searcher.search_with_context(
            query=query.query,
            repo_id=query.repo_id,
            limit=query.limit,
        )
        return CodeContextResponse(context=context, success=True)
    except Exception as exc:
        return CodeContextResponse(
            context=None,
            success=False,
            error=str(exc),
        )


@router.get("/history", response_model=List[SearchHistoryResponse])
def search_history(
    repo_id: Optional[UUID] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> List[SearchHistory]:
    q = db.query(SearchHistory)
    if repo_id:
        q = q.filter(SearchHistory.repo_id == repo_id)
    return q.order_by(SearchHistory.created_at.desc()).limit(limit).all()


@router.post("/benchmark", response_model=BenchmarkResponse)
def create_benchmark(
    payload: BenchmarkCreate, db: Session = Depends(get_db)
) -> BenchmarkResponse:
    service = BenchmarkService(db)
    return service.run_benchmark(payload)


@router.get("/benchmark", response_model=List[BenchmarkResponse])
def list_benchmarks(
    repo_id: Optional[UUID] = None,
    mode: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[BenchmarkResponse]:
    service = BenchmarkService(db)
    return service.list_benchmarks(repo_id, mode, limit)


@router.get("/benchmark/summary", response_model=BenchmarkSummary)
def benchmark_summary(
    repo_id: Optional[UUID] = None,
    days: int = 7,
    db: Session = Depends(get_db),
) -> dict:
    service = BenchmarkService(db)
    return service.get_summary(repo_id, days)


@router.get("/history/stats", response_model=SearchHistoryStats)
def search_history_stats(
    repo_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated search history stats for the current day."""
    from datetime import date, datetime, timezone, timedelta

    today = date.today()
    local_start = datetime.combine(today, datetime.min.time())
    utc_offset = datetime.now(timezone.utc).astimezone().utcoffset() or timedelta(0)
    utc_start = (local_start - utc_offset).replace(tzinfo=timezone.utc)
    q = db.query(SearchHistory).filter(SearchHistory.created_at >= utc_start)
    if repo_id:
        q = q.filter(SearchHistory.repo_id == repo_id)

    rows = q.all()
    total_queries = len(rows)
    avg_latency = sum(r.latency_ms for r in rows) / max(1, total_queries)
    total_input = sum(r.input_tokens for r in rows)
    total_output = sum(r.output_tokens for r in rows)

    # Baseline assumption: without CodePop, an LLM would read ~20k tokens per query.
    baseline_tokens_per_query = 20000
    estimated_baseline = total_queries * baseline_tokens_per_query
    estimated_tokens_saved = max(0, estimated_baseline - (total_input + total_output))

    return {
        "total_queries": total_queries,
        "avg_latency_ms": round(avg_latency, 2),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "estimated_tokens_saved": estimated_tokens_saved,
    }
