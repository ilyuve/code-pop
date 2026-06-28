"""Offline benchmark script for CodePop retrieval quality.

Usage:
    python -m scripts.benchmark path/to/benchmark_queries.json --repo-id <uuid>

benchmark_queries.json format:
[
  {
    "query": "how is authentication handled?",
    "expected_files": ["src/auth.py"],
    "expected_lines": [42]
  }
]
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from database import SessionLocal
from models import CodeFile
from services.searcher import Searcher


def _load_queries(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("queries", [])
    return data


def _is_relevant(result: Any, expected_files: List[str], expected_lines: List[int]) -> bool:
    file_path = getattr(result, "file_path", "")
    line = getattr(result, "line", 0)
    for expected in expected_files:
        if expected.lower() in file_path.lower():
            return True
    if line in expected_lines:
        return True
    return False


def _baseline_keyword_search(db: Session, query: str, repo_id: UUID | None, limit: int = 20):
    """Naive baseline: keyword AND scan over all file contents."""
    start = time.perf_counter()
    q = db.query(CodeFile)
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
    return matches[:limit], latency_ms


def run_benchmark(
    db: Session,
    queries: List[Dict[str, Any]],
    repo_id: UUID | None,
    k: int = 10,
) -> Dict[str, Any]:
    searcher = Searcher(db)
    per_query: List[Dict[str, Any]] = []
    hybrid_latencies: List[int] = []
    baseline_latencies: List[int] = []

    for item in queries:
        query = item["query"]
        expected_files = item.get("expected_files", [])
        expected_lines = item.get("expected_lines", [])

        # Hybrid search.
        h_start = time.perf_counter()
        hybrid_results = searcher.hybrid_search(query, repo_id, limit=k)
        h_latency = int((time.perf_counter() - h_start) * 1000)
        hybrid_latencies.append(h_latency)

        relevant_at_k = sum(1 for r in hybrid_results[:k] if _is_relevant(r, expected_files, expected_lines))
        recall_at_k = relevant_at_k / max(1, len(expected_files) + len(expected_lines))
        first_relevant_rank = None
        for idx, r in enumerate(hybrid_results[:k], start=1):
            if _is_relevant(r, expected_files, expected_lines):
                first_relevant_rank = idx
                break
        rr = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

        # Baseline.
        baseline_results, b_latency = _baseline_keyword_search(db, query, repo_id, limit=k)
        baseline_latencies.append(b_latency)

        per_query.append(
            {
                "query": query,
                "hybrid_latency_ms": h_latency,
                "hybrid_results_count": len(hybrid_results),
                "hybrid_relevant_at_k": relevant_at_k,
                "recall_at_k": round(recall_at_k, 3),
                "mrr": round(rr, 3),
                "baseline_latency_ms": b_latency,
                "baseline_results_count": len(baseline_results),
            }
        )

    summary = {
        "total_queries": len(queries),
        "k": k,
        "avg_hybrid_latency_ms": round(statistics.mean(hybrid_latencies), 2) if hybrid_latencies else 0,
        "p95_hybrid_latency_ms": round(statistics.quantiles(hybrid_latencies, n=20)[18], 2) if len(hybrid_latencies) >= 20 else None,
        "p50_hybrid_latency_ms": round(statistics.median(hybrid_latencies), 2) if hybrid_latencies else 0,
        "avg_baseline_latency_ms": round(statistics.mean(baseline_latencies), 2) if baseline_latencies else 0,
        "avg_recall_at_k": round(statistics.mean([r["recall_at_k"] for r in per_query]), 3) if per_query else 0,
        "avg_mrr": round(statistics.mean([r["mrr"] for r in per_query]), 3) if per_query else 0,
        "per_query": per_query,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="CodePop offline benchmark")
    parser.add_argument("queries", help="Path to benchmark_queries.json")
    parser.add_argument("--repo-id", help="Optional repo UUID to restrict search")
    parser.add_argument("--k", type=int, default=10, help="Top-K for recall/mrr")
    parser.add_argument("--output", default="benchmark_report.json", help="Output report path")
    args = parser.parse_args()

    queries = _load_queries(args.queries)
    repo_id = UUID(args.repo_id) if args.repo_id else None

    db = SessionLocal()
    try:
        report = run_benchmark(db, queries, repo_id, k=args.k)
    finally:
        db.close()

    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Benchmark report written to {output_path}")
    print(f"Avg hybrid latency: {report['avg_hybrid_latency_ms']}ms")
    print(f"Avg baseline latency: {report['avg_baseline_latency_ms']}ms")
    print(f"Avg recall@{args.k}: {report['avg_recall_at_k']}")
    print(f"Avg MRR: {report['avg_mrr']}")


if __name__ == "__main__":
    main()
