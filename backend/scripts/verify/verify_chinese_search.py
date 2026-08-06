"""End-to-end verification of Chinese semantic code retrieval.

Runs a fixed set of Chinese (and mixed) queries against the live database and
checks that the retrieval pipeline returns semantically relevant results.

Usage:
    uv run python scripts/verify/verify_chinese_search.py --repo-id <uuid>
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal
from services.searcher import Searcher


# Test cases: (query, expected_keywords_in_top3, check_type)
# expected_keywords: at least one should appear in top-3 results (symbol name or file path)
# check_type: "any" = at least one keyword in top-3; "entry_point" = first entry_point matches
TEST_CASES = [
    ("订单创建流程", ["createOrder", "OrderService", "OrderRepository", "order"], "any"),
    ("redis 缓存配置", ["RedisConfig", "CacheConfig", "RedisCache", "redis", "cache"], "any"),
    ("jwt token 怎么生成", ["generateToken", "JwtToken", "TokenService", "jwt", "token"], "any"),
    ("骑手派单接口", ["dispatchOrder", "RiderService", "RiderController", "rider", "dispatch"], "any"),
    ("OrderService.createOrder", ["OrderService", "createOrder"], "any"),
]


def _check_keywords_in_results(results: List[Dict[str, Any]], keywords: List[str], top_k: int = 3) -> bool:
    """Check if any keyword appears in top-k results."""
    top_results = results[:top_k]
    for item in top_results:
        text = f"{item.get('symbol_name', '')} {item.get('file_path', '')} {item.get('content', '')}".lower()
        for kw in keywords:
            if kw.lower() in text:
                return True
    return False


def _check_entry_point(entry_points: List[Dict[str, Any]], keywords: List[str]) -> bool:
    """Check if the first entry point matches any keyword."""
    if not entry_points:
        return False
    first = entry_points[0]
    text = f"{first.get('name', '')} {first.get('chinese_name', '')} {first.get('file_path', '')}".lower()
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False


def verify_query(searcher: Searcher, query: str, repo_id: Optional[UUID], expected_keywords: List[str]) -> Dict[str, Any]:
    """Run one verification query and return structured result."""
    try:
        context = searcher.search_with_context(query, repo_id=repo_id, limit=20)
    except Exception as e:
        return {
            "query": query,
            "success": False,
            "error": str(e),
            "top3_results": [],
            "entry_points": [],
            "score_breakdown_summary": {},
        }

    top3 = []
    for item in context.code_snippets[:3]:
        top3.append({
            "file_path": item.file_path,
            "line": item.line,
            "score": item.score,
            "score_breakdown": item.score_breakdown,
        })

    entry_points = []
    for ep in context.entry_points[:5]:
        entry_points.append({
            "name": ep.name,
            "chinese_name": ep.chinese_name,
            "file_path": ep.file_path,
            "relevance_score": ep.relevance_score,
        })

    # Aggregate score breakdown to see which sources fired.
    breakdown_summary = {"vector": 0, "symbol": 0, "bm25": 0, "sparse": 0, "graph": 0, "rrf": 0}
    for item in context.code_snippets:
        bd = item.score_breakdown or {}
        for key in breakdown_summary:
            breakdown_summary[key] += 1 if bd.get(key, 0) > 0 else 0

    keyword_hit = _check_keywords_in_results(
        [{"symbol_name": "", "file_path": item.file_path, "content": item.content} for item in context.code_snippets[:3]],
        expected_keywords,
    )
    entry_point_hit = _check_entry_point(
        [{"name": ep.name, "chinese_name": ep.chinese_name, "file_path": ep.file_path} for ep in context.entry_points],
        expected_keywords,
    )

    # Success criteria: keyword found in top-3 OR first entry point is relevant.
    # Also require at least one non-zero source score.
    success = (keyword_hit or entry_point_hit) and any(
        v > 0 for v in breakdown_summary.values()
    )

    return {
        "query": query,
        "success": success,
        "keyword_hit": keyword_hit,
        "entry_point_hit": entry_point_hit,
        "top3_results": top3,
        "entry_points": entry_points,
        "score_breakdown_summary": breakdown_summary,
        "call_chain_root": context.call_chain.root.name if context.call_chain and context.call_chain.root else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Chinese semantic code retrieval")
    parser.add_argument("--repo-id", type=str, default=None, help="Repository UUID to search")
    parser.add_argument("--output", type=str, default=None, help="Write JSON report to this path")
    args = parser.parse_args()

    repo_id = UUID(args.repo_id) if args.repo_id else None

    db = SessionLocal()
    searcher = Searcher(db)

    results = []
    passed = 0
    failed = 0

    print("=" * 70)
    print("Chinese Semantic Retrieval Verification")
    print("=" * 70)

    for query, expected_keywords, check_type in TEST_CASES:
        print(f"\nQuery: {query}")
        print(f"  Expected keywords: {expected_keywords}")

        result = verify_query(searcher, query, repo_id, expected_keywords)
        results.append(result)

        if result["success"]:
            passed += 1
            print("  [PASS]")
        else:
            failed += 1
            print("  [FAIL]")

        if result.get("error"):
            print(f"  Error: {result['error']}")

        print(f"  Keyword hit in top-3: {result.get('keyword_hit', False)}")
        print(f"  Entry point hit: {result.get('entry_point_hit', False)}")
        print(f"  Score breakdown summary: {result.get('score_breakdown_summary', {})}")

        if result.get("top3_results"):
            print("  Top 3 results:")
            for i, r in enumerate(result["top3_results"], 1):
                print(f"    {i}. {r['file_path']}:{r['line']} score={r['score']:.4f}")

        if result.get("entry_points"):
            print("  Entry points:")
            for i, ep in enumerate(result["entry_points"], 1):
                cn = f" ({ep['chinese_name']})" if ep.get("chinese_name") else ""
                print(f"    {i}. {ep['name']}{cn} @ {ep['file_path']} score={ep['relevance_score']:.4f}")

        if result.get("call_chain_root"):
            print(f"  Call chain root: {result['call_chain_root']}")

    print("\n" + "=" * 70)
    print(f"Summary: {passed} passed, {failed} failed out of {len(TEST_CASES)}")
    print("=" * 70)

    report = {
        "total": len(TEST_CASES),
        "passed": passed,
        "failed": failed,
        "results": results,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport written to {args.output}")

    db.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
