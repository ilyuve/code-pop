"""Benchmark service layer."""

import time
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import BenchmarkRun, CodeFile
from schemas import BenchmarkCreate, BenchmarkSummary
from services.embedder import Embedder
from services.searcher import Searcher


class BenchmarkService:
    """Handles benchmark execution and reporting."""

    def __init__(self, db: Session, searcher: Optional[Searcher] = None):
        self.db = db
        self.searcher = searcher or Searcher(db)
        self.embedder = Embedder()

    def _estimate_output_tokens(self, results: List) -> int:
        """Estimate output tokens from result contents."""
        total_chars = sum(len(getattr(r, "content", "")) for r in results)
        return max(0, total_chars // 4)

    def _baseline_keyword_search(self, query: str, repo_id: Optional[UUID], limit: int = 20):
        """Naive baseline: keyword AND scan over file contents."""
        start = time.perf_counter()
        q = self.db.query(CodeFile)
        if repo_id:
            q = q.filter(CodeFile.repo_id == repo_id)
        files = q.all()
        keywords = query.lower().split()
        matches = []
        for f in files:
            try:
                content = Path(f.repo.local_path, f.path).read_text(errors="ignore")
            except Exception:
                content = ""
            if all(kw in content.lower() for kw in keywords):
                matches.append(f)
        latency_ms = int((time.perf_counter() - start) * 1000)
        token_consumed = 0
        for f in matches[:limit]:
            try:
                token_consumed += self.embedder.count_tokens(
                    Path(f.repo.local_path, f.path).read_text(errors="ignore") or ""
                )
            except Exception:
                pass
        return matches[:limit], latency_ms, token_consumed

    def run_benchmark(self, payload: BenchmarkCreate) -> BenchmarkRun:
        """Run a single benchmark and persist results."""
        start = time.perf_counter()

        if payload.mode == "without_codepop":
            results, latency_ms, token_consumed = self._baseline_keyword_search(
                payload.query, payload.repo_id, limit=20
            )
            relevant = 0
            expected_files_lower = {f.lower() for f in payload.expected_files}
            for f in results:
                if any(exp in f.path.lower() for exp in expected_files_lower):
                    relevant += 1
        else:
            search_results = self.searcher.hybrid_search(payload.query, payload.repo_id, 20)
            latency_ms = int((time.perf_counter() - start) * 1000)
            results = search_results
            token_consumed = self._estimate_output_tokens(search_results)
            relevant = 0
            expected_files_lower = {f.lower() for f in payload.expected_files}
            for r in results:
                if any(exp in r.file_path.lower() for exp in expected_files_lower):
                    relevant += 1
                if r.line in payload.expected_lines:
                    relevant += 1

        accuracy_score = 0.0
        if results:
            accuracy_score = min(
                1.0,
                relevant / max(1, len(payload.expected_files) + len(payload.expected_lines)),
            )

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
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def list_benchmarks(
        self, repo_id: Optional[UUID] = None, mode: Optional[str] = None, limit: int = 100
    ) -> List[BenchmarkRun]:
        q = self.db.query(BenchmarkRun)
        if repo_id:
            q = q.filter(BenchmarkRun.repo_id == repo_id)
        if mode:
            q = q.filter(BenchmarkRun.mode == mode)
        return q.order_by(BenchmarkRun.created_at.desc()).limit(limit).all()

    def get_summary(self, repo_id: Optional[UUID] = None, days: int = 7) -> BenchmarkSummary:
        q = self.db.query(BenchmarkRun)
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
                "latency_percent": 0
                if without_latency == 0
                else round((without_latency - with_latency) / without_latency * 100, 2),
                "token_percent": 0
                if without_tokens == 0
                else round((without_tokens - with_tokens) / without_tokens * 100, 2),
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
