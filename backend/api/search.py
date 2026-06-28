"""Search endpoints."""

import time
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import settings
from database import get_db
from models import BenchmarkRun, SearchHistory
from schemas import (
    BenchmarkCreate,
    BenchmarkResponse,
    BenchmarkSummary,
    SearchHistoryResponse,
    SearchHistoryStats,
    SearchQuery,
    SearchResultItem,
    SymbolSearchQuery,
)
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
    repo_id: UUID | None,
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


@router.get("/history", response_model=List[SearchHistoryResponse])
def search_history(
    repo_id: UUID | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> List[SearchHistory]:
    q = db.query(SearchHistory)
    if repo_id:
        q = q.filter(SearchHistory.repo_id == repo_id)
    return q.order_by(SearchHistory.created_at.desc()).limit(limit).all()


def _run_benchmark(
    db: Session, payload: BenchmarkCreate
) -> BenchmarkRun:
    """Run a single benchmark and persist results."""
    start = time.perf_counter()
    searcher = Searcher(db)

    if payload.mode == "without_codepop":
        # Baseline: naive keyword scan over file contents.
        from models import CodeFile

        q = db.query(CodeFile)
        if payload.repo_id:
            q = q.filter(CodeFile.repo_id == payload.repo_id)
        files = q.all()
        keywords = payload.query.lower().split()
        matches = []
        for f in files:
            # Try to read the actual file content for a fairer baseline.
            try:
                from pathlib import Path

                content = Path(f.repo.local_path, f.path).read_text(errors="ignore")
            except Exception:
                content = ""
            if all(kw in content.lower() for kw in keywords):
                matches.append(f)
        results = matches[:20]
        latency_ms = int((time.perf_counter() - start) * 1000)
        token_consumed = sum(embedder.count_tokens(Path(f.repo.local_path, f.path).read_text(errors="ignore") or "") for f in results)
    else:
        search_results = searcher.hybrid_search(payload.query, payload.repo_id, 20)
        latency_ms = int((time.perf_counter() - start) * 1000)
        results = search_results
        token_consumed = _estimate_output_tokens(search_results)

    # Compute relevance: intersection with expected files / lines.
    relevant = 0
    expected_files_lower = {f.lower() for f in payload.expected_files}
    if payload.mode == "without_codepop":
        for f in results:
            if any(exp in f.path.lower() for exp in expected_files_lower):
                relevant += 1
    else:
        for r in results:
            if any(exp in r.file_path.lower() for exp in expected_files_lower):
                relevant += 1
            if r.line in payload.expected_lines:
                relevant += 1

    accuracy_score = 0.0
    if results:
        accuracy_score = min(1.0, relevant / max(1, len(payload.expected_files) + len(payload.expected_lines)))

    run = BenchmarkRun(
        query=payload.query,
        repo_id=payload.repo_id,
        mode=payload.mode,
        latency_ms=latency_ms,
        results_count=len(results),
        relevant_results_count=relevant,
        token_consumed=token_consumed,
        accuracy_score=int(accuracy_score * 100),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.post("/benchmark", response_model=BenchmarkResponse)
def create_benchmark(
    payload: BenchmarkCreate, db: Session = Depends(get_db)
) -> BenchmarkRun:
    return _run_benchmark(db, payload)


@router.get("/benchmark", response_model=List[BenchmarkResponse])
def list_benchmarks(
    repo_id: UUID | None = None,
    mode: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[BenchmarkRun]:
    q = db.query(BenchmarkRun)
    if repo_id:
        q = q.filter(BenchmarkRun.repo_id == repo_id)
    if mode:
        q = q.filter(BenchmarkRun.mode == mode)
    return q.order_by(BenchmarkRun.created_at.desc()).limit(limit).all()


@router.get("/benchmark/summary", response_model=BenchmarkSummary)
def benchmark_summary(
    repo_id: UUID | None = None,
    days: int = 7,
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(BenchmarkRun)
    if repo_id:
        q = q.filter(BenchmarkRun.repo_id == repo_id)

    total_runs = q.count()
    avg_latency = q.with_entities(func.avg(BenchmarkRun.latency_ms)).scalar() or 0
    avg_tokens = q.with_entities(func.avg(BenchmarkRun.token_consumed)).scalar() or 0
    avg_accuracy = q.with_entities(func.avg(BenchmarkRun.accuracy_score)).scalar() or 0

    trend = (
        q.order_by(BenchmarkRun.created_at.asc())
        .limit(50)
        .with_entities(BenchmarkRun.created_at, BenchmarkRun.latency_ms)
        .all()
    )

    with_runs = q.filter(BenchmarkRun.mode == "with_codepop").all()
    without_runs = q.filter(BenchmarkRun.mode == "without_codepop").all()

    with_latency = sum(r.latency_ms for r in with_runs) / max(1, len(with_runs))
    without_latency = sum(r.latency_ms for r in without_runs) / max(1, len(without_runs))
    with_tokens = sum(r.token_consumed for r in with_runs) / max(1, len(with_runs))
    without_tokens = sum(r.token_consumed for r in without_runs) / max(1, len(without_runs))

    savings = {}
    if with_runs and without_runs:
        savings = {
            "latency_ms": max(0, without_latency - with_latency),
            "token_consumed": max(0, without_tokens - with_tokens),
            "latency_percent": 0 if without_latency == 0 else round((without_latency - with_latency) / without_latency * 100, 2),
            "token_percent": 0 if without_tokens == 0 else round((without_tokens - with_tokens) / without_tokens * 100, 2),
        }

    return {
        "total_runs": total_runs,
        "avg_latency_ms": round(avg_latency, 2),
        "avg_token_consumed": round(avg_tokens, 2),
        "avg_accuracy_score": round(avg_accuracy / 100, 2),
        "latency_trend": [
            {"timestamp": r.created_at.isoformat(), "latency_ms": r.latency_ms}
            for r in trend
        ],
        "savings_vs_baseline": savings,
    }


@router.get("/history/stats", response_model=SearchHistoryStats)
def search_history_stats(
    repo_id: UUID | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated search history stats for the current day."""
    from datetime import date, datetime

    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    q = db.query(SearchHistory).filter(SearchHistory.created_at >= start)
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
