"""端到端主流程测试脚本：源码文件/目录 -> 解析 -> 中文增强 -> 向量 -> 4路召回 -> 上层结果。

不需要数据库，不需要入库，直接在内存中跑完整个检索主流程。

默认使用真实 LLM（OpenAI-compatible，如 DeepSeek）做中文增强，使用真实 BGE-M3 做向量编码，
与生产主流程保持一致。只有在显式加 --mock-llm 或 --mock-embedder 时才会降级为 mock。

用法示例（默认真实 LLM + 真实 embedder）：
    cd /workspace/backend
    export LLM_BASE_URL=https://api.deepseek.com/v1
    export LLM_API_KEY=$DEEPSEEK_API_KEY
    export LLM_MODEL=deepseek-chat
    python -m scripts.verify.test_e2e_retrieval /path/to/project \
        --query "订单创建流程" \
        --query "create order logic"

用法示例（显式传入 LLM 参数）：
    cd /workspace/backend
    python -m scripts.verify.test_e2e_retrieval /path/to/project \
        --query "订单创建流程" \
        --llm-base-url https://api.deepseek.com/v1 \
        --llm-api-key $DEEPSEEK_API_KEY \
        --llm-model deepseek-chat

用法示例（仅 mock embedder，验证 pipeline 逻辑）：
    cd /workspace/backend
    python -m scripts.verify.test_e2e_retrieval /path/to/project \
        --query "订单创建流程" \
        --mock-embedder

用法示例（全部 mock，仅做冒烟测试）：
    cd /workspace/backend
    python -m scripts.verify.test_e2e_retrieval /path/to/project \
        --query "订单创建流程" \
        --mock-llm \
        --mock-embedder

输出：JSON 格式的检索结果，包含 entry_points、code_snippets、score_breakdown。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

# Ensure backend/ is on the path when the script is run as a module or directly.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.chinese_enricher import EnrichmentResult, enrich_chunk
from services.embedder import Embedder
from services.parser import Chunk, ParseResult, Symbol, list_source_files, parse_file
from services.query_intent import QueryIntentAnalyzer
from services.llm_client import LLMChatResponse, LLMClient, encrypt_api_key

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# In-memory data structures (replace DB rows)
# ---------------------------------------------------------------------------


@dataclass
class MemEmbedding:
    """In-memory replacement for the Embedding ORM row."""

    id: UUID
    file_path: str
    language: str
    content: str
    enriched_text: str
    start_line: int
    end_line: int
    dense: List[float]
    sparse: Dict[int, float]
    enrichment: Optional[EnrichmentResult] = None
    symbols: List[Symbol] = field(default_factory=list)


@dataclass
class MemSymbol:
    """In-memory replacement for the Symbol ORM row, linked to an embedding."""

    id: UUID
    name: str
    type: str
    kind: str
    line: int
    file_path: str
    embedding_id: UUID


# ---------------------------------------------------------------------------
# Optional mock embedder: lets you validate the pipeline without downloading
# the full BGE-M3 model (useful in CI / disk-constrained sandboxes).
# ---------------------------------------------------------------------------


class MockEmbedder:
    """Deterministic mock embedder for end-to-end pipeline validation.

    Dense vectors are random unit vectors; sparse vectors are simple token-hash
    bags.  Symbol/BM25 recall remain real, so you can still verify ranking logic.
    """

    def __init__(self, dim: int = 1024, seed: int = 42):
        import numpy as np

        self.dim = dim
        self.rng = np.random.default_rng(seed)

    def encode(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        import numpy as np

        vectors = self.rng.standard_normal((len(texts), self.dim)).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.where(norms == 0, 1.0, norms)
        return vectors.tolist()

    def encode_sparse(self, texts: List[str]) -> List[Dict[int, float]]:
        results = []
        for text in texts:
            tokens = set(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text.lower()))
            sparse = {}
            for token in tokens:
                tid = hash(token) % 100000
                weight = 1.0 + math.log1p(len(token))
                sparse[tid] = weight
            results.append(sparse)
        return results

    def encode_query(self, text: str) -> List[float]:
        return self.encode([text], is_query=True)[0]

    def encode_query_sparse(self, text: str) -> Dict[int, float]:
        return self.encode_sparse([text])[0]

    def encode_documents(self, texts: List[str]) -> List[List[float]]:
        return self.encode(texts, is_query=False)


# ---------------------------------------------------------------------------
# Lightweight LLM routers (no database required)
# ---------------------------------------------------------------------------


class MockLLMRouter:
    """A no-op LLM router that returns plausible enrichment JSON instantly.

    Use this to test the pipeline when you do not want to call an online LLM.
    """

    async def chat(
        self,
        messages: List[Dict[str, str]],
        operation: str = "chat",
        repo_id: Optional[str] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Tuple[LLMChatResponse, str]:
        content = messages[-1]["content"]

        # Try to extract a function/class name to make the mock a bit more realistic.
        name_match = re.search(r"(?:def|class|function|void|int|String)\s+(\w+)", content)
        name = name_match.group(1) if name_match else "unknown"

        if operation == "enrich_chunk":
            payload = {
                "chinese_summary": f"该代码块实现了 {name} 相关逻辑",
                "keywords": ["代码", name, "实现", "逻辑"],
                "vertical_layer": "service",
                "horizontal_module": "order",
                "synonyms": {},
            }
        elif operation == "enrich_symbol_flow":
            payload = {
                "layer": "service",
                "module": "order",
                "chinese_name": name[:6] or "未知",
                "io_description": f"处理 {name} 的输入输出",
            }
        else:
            payload = {"synonyms": [], "code_terms": []}

        return (
            LLMChatResponse(
                content=json.dumps(payload, ensure_ascii=False),
                input_tokens=0,
                output_tokens=0,
                model="mock",
                latency_ms=0,
            ),
            "mock",
        )


class LocalLLMRouter:
    """A tiny OpenAI-compatible router that does NOT need a database.

    It builds an in-memory LlmProvider-like object and reuses the production
    LLMClient so the prompt / JSON-mode behaviour is identical to the main app.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        provider_type: str = "openai_compatible",
    ):
        self.provider_id = uuid4()
        self.provider = SimpleNamespace(
            id=self.provider_id,
            name="local-test",
            provider_type=provider_type,
            base_url=base_url,
            api_key=encrypt_api_key(api_key),
            model=model,
            capability="chat",
            max_tokens=4096,
            temperature=0.1,
            timeout_seconds=120,
            extra_headers=None,
            extra_body=None,
        )
        self._client = LLMClient(self.provider)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        operation: str = "chat",
        repo_id: Optional[str] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Tuple[LLMChatResponse, str]:
        resp = await self._client.chat(messages, response_format=response_format)
        return resp, str(self.provider_id)


# ---------------------------------------------------------------------------
# Indexing stage (parse + enrich + embed) in memory
# ---------------------------------------------------------------------------


def _build_enriched_text(content: str, enrichment: Optional[EnrichmentResult]) -> str:
    """Same logic as indexer._build_enriched_text."""
    if not enrichment:
        return content
    parts = []
    if enrichment.chinese_summary:
        parts.append(f"【中文摘要】{enrichment.chinese_summary}")
    if enrichment.keywords:
        parts.append(f"【关键词】{', '.join(enrichment.keywords)}")
    if parts:
        return "\n".join(parts) + "\n\n" + content
    return content


async def _enrich_chunks(
    router,
    parse_result: ParseResult,
) -> Dict[str, EnrichmentResult]:
    """Run Chinese enrichment for every chunk."""
    results: Dict[str, EnrichmentResult] = {}
    semaphore = asyncio.Semaphore(5)

    async def enrich_one(chunk: Chunk) -> None:
        async with semaphore:
            result = await enrich_chunk(
                router,
                chunk.content,
                parse_result.language,
                repo_id=None,
            )
            if result:
                h = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
                results[h] = result

    await asyncio.gather(*[enrich_one(chunk) for chunk in parse_result.chunks])
    return results


def _index_file_in_memory(
    file_path: str,
    content: str,
    router,
    embedder: Embedder,
) -> Tuple[List[MemEmbedding], List[MemSymbol]]:
    """Parse, optionally enrich, encode and return in-memory embeddings + symbols."""
    parsed = parse_file(file_path, content)
    if parsed is None:
        raise RuntimeError(f"Failed to parse {file_path}; is it a supported language?")

    logger.info(
        "Parsed %s: language=%s symbols=%d chunks=%d",
        file_path,
        parsed.language,
        len(parsed.symbols),
        len(parsed.chunks),
    )

    # 1. Chinese semantic enrichment
    loop = asyncio.get_event_loop()
    enrichments = loop.run_until_complete(_enrich_chunks(router, parsed))

    # 2. Build texts for embedding
    texts_to_embed: List[str] = []
    meta: List[Tuple[Chunk, str]] = []  # (chunk, chunk_hash)
    for chunk in parsed.chunks:
        h = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        enrichment = enrichments.get(h)
        texts_to_embed.append(_build_enriched_text(chunk.content, enrichment))
        meta.append((chunk, h))

    # 3. Dense + sparse vectors
    dense_vectors = embedder.encode_documents(texts_to_embed)
    sparse_vectors = embedder.encode_sparse(texts_to_embed)

    # 4. Build memory records
    embeddings: List[MemEmbedding] = []
    for idx, ((chunk, h), dense, sparse) in enumerate(
        zip(meta, dense_vectors, sparse_vectors)
    ):
        emb_id = uuid4()
        enrichment = enrichments.get(h)
        embeddings.append(
            MemEmbedding(
                id=emb_id,
                file_path=file_path,
                language=parsed.language,
                content=chunk.content,
                enriched_text=texts_to_embed[idx],
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                dense=dense,
                sparse=sparse,
                enrichment=enrichment,
                symbols=[
                    s
                    for s in parsed.symbols
                    if chunk.start_line <= s.line <= chunk.end_line
                ],
            )
        )

    # Link symbols to the best embedding (the one whose span contains the symbol line).
    symbol_rows: List[MemSymbol] = []
    for sym in parsed.symbols:
        target_emb = None
        for emb in embeddings:
            if emb.start_line <= sym.line <= emb.end_line:
                target_emb = emb
                break
        if target_emb is None and embeddings:
            target_emb = embeddings[0]
        if target_emb is not None:
            symbol_rows.append(
                MemSymbol(
                    id=uuid4(),
                    name=sym.name,
                    type=sym.type,
                    kind=sym.kind,
                    line=sym.line,
                    file_path=file_path,
                    embedding_id=target_emb.id,
                )
            )

    return embeddings, symbol_rows


# ---------------------------------------------------------------------------
# In-memory retrieval (4-way recall)
# ---------------------------------------------------------------------------


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _sparse_dot(a: Dict[int, float], b: Dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    return sum(a.get(k, 0.0) * v for k, v in b.items())


def _normalize_symbol(name: str) -> str:
    # CamelCase / snake_case / kebab-case / dot.case -> lowercase tokens
    tokens = re.split(r"[_\-.]", name)
    expanded = []
    for token in tokens:
        expanded.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", token))
    return " ".join(t.lower() for t in expanded if t)


def _symbol_matches(query_terms: List[str], symbol_name: str) -> float:
    normalized = _normalize_symbol(symbol_name)
    normalized_set = set(normalized.split())
    for term in query_terms:
        t = term.lower()
        if t == symbol_name.lower():
            return 1.0
        if t in normalized_set:
            return 0.9
        if t in normalized:
            return 0.7
    return 0.0


def _bm25_score(query_terms: List[str], text: str) -> float:
    """A simple in-memory keyword overlap score (PG to_tsvector replacement)."""
    text_lower = text.lower()
    score = 0.0
    for term in query_terms:
        score += text_lower.count(term.lower()) * (1.0 + math.log1p(len(term)))
    return score


def _vector_search(
    query_embedding: List[float],
    embeddings: List[MemEmbedding],
    top_k: int,
) -> List[Tuple[MemEmbedding, float]]:
    scored = [(emb, _cosine(query_embedding, emb.dense)) for emb in embeddings]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _symbol_search(
    query_terms: List[str],
    symbols: List[MemSymbol],
    embeddings: List[MemEmbedding],
    top_k: int,
) -> List[Tuple[MemEmbedding, float]]:
    emb_by_id = {emb.id: emb for emb in embeddings}
    scored: Dict[UUID, float] = {}
    for sym in symbols:
        score = _symbol_matches(query_terms, sym.name)
        if score > 0:
            emb = emb_by_id.get(sym.embedding_id)
            if emb:
                scored[emb.id] = max(scored.get(emb.id, 0.0), score)
    results = [(emb_by_id[eid], s) for eid, s in scored.items()]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def _bm25_search(
    query_terms: List[str],
    embeddings: List[MemEmbedding],
    top_k: int,
) -> List[Tuple[MemEmbedding, float]]:
    scored = []
    for emb in embeddings:
        text = emb.enriched_text or emb.content
        score = _bm25_score(query_terms, text)
        if score > 0:
            scored.append((emb, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _sparse_search(
    query_sparse: Dict[int, float],
    embeddings: List[MemEmbedding],
    top_k: int,
) -> List[Tuple[MemEmbedding, float]]:
    scored = [(emb, _sparse_dot(query_sparse, emb.sparse)) for emb in embeddings]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _rrk_fuse(
    source_results: Dict[str, List[Tuple[MemEmbedding, float]]],
    k: int = 60,
) -> List[Tuple[MemEmbedding, float]]:
    """Reciprocal rank fusion across multiple retrieval sources."""
    rrf: Dict[UUID, float] = {}
    emb_by_id: Dict[UUID, MemEmbedding] = {}
    for source, hits in source_results.items():
        for rank, (emb, _score) in enumerate(hits, start=1):
            emb_by_id[emb.id] = emb
            rrf[emb.id] = rrf.get(emb.id, 0.0) + 1.0 / (k + rank)
    sorted_ids = sorted(rrf.keys(), key=lambda eid: -rrf[eid])
    return [(emb_by_id[eid], rrf[eid]) for eid in sorted_ids]


# ---------------------------------------------------------------------------
# Main pipeline: query -> intent -> 4-way recall -> CodeContext-like output
# ---------------------------------------------------------------------------


def _run_query(
    query: str,
    embeddings: List[MemEmbedding],
    symbols: List[MemSymbol],
    embedder: Embedder,
    llm_router,
) -> Dict[str, Any]:
    analyzer = QueryIntentAnalyzer()
    intent = analyzer.analyze(
        query,
        repo_id=None,
        db=None,
        enable_llm_expand=llm_router is not None,
        llm_router=llm_router,
    )

    # Use expanded terms for lexical sources (symbol + bm25 + sparse token overlap).
    search_terms = intent.expanded_terms if intent.search_strategy.expand_synonyms else [query]
    # Limit expansion to avoid noise.
    search_terms = search_terms[:5]

    # Encode query for vector / sparse retrieval.
    query_dense = embedder.encode_query(query)
    query_sparse = embedder.encode_query_sparse(query)

    # 4-way recall
    vector_hits = _vector_search(query_dense, embeddings, top_k=20)
    symbol_hits = _symbol_search(search_terms, symbols, embeddings, top_k=20)
    bm25_hits = _bm25_search(search_terms, embeddings, top_k=20)
    sparse_hits = _sparse_search(query_sparse, embeddings, top_k=20)

    source_results = {
        "vector": vector_hits,
        "symbol": symbol_hits,
        "bm25": bm25_hits,
        "sparse": sparse_hits,
    }

    fused = _rrk_fuse(source_results)

    # Normalize per-source scores for the breakdown.
    def _norm(scored: List[Tuple[MemEmbedding, float]]) -> Dict[UUID, float]:
        if not scored:
            return {}
        scores = [s for _, s in scored]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return {emb.id: 1.0 for emb, _ in scored}
        return {emb.id: (s - min_s) / (max_s - min_s) for emb, s in scored}

    vector_norm = _norm(vector_hits)
    symbol_norm = _norm(symbol_hits)
    bm25_norm = _norm(bm25_hits)
    sparse_norm = _norm(sparse_hits)

    # Build upper-layer output similar to schemas.CodeContext.
    code_snippets = []
    entry_points = []
    seen_symbols: Set[str] = set()

    for emb, rrf_score in fused[:10]:
        snippet = {
            "id": str(emb.id),
            "file_path": emb.file_path,
            "language": emb.language,
            "line": emb.start_line,
            "content": emb.content[:500],
            "score": round(rrf_score, 4),
            "score_breakdown": {
                "vector": round(vector_norm.get(emb.id, 0.0), 4),
                "symbol": round(symbol_norm.get(emb.id, 0.0), 4),
                "bm25": round(bm25_norm.get(emb.id, 0.0), 4),
                "sparse": round(sparse_norm.get(emb.id, 0.0), 4),
                "rrf": round(rrf_score, 4),
            },
        }
        code_snippets.append(snippet)

        for sym in emb.symbols[:3]:
            key = f"{sym.type}:{sym.name}:{sym.line}"
            if key not in seen_symbols:
                seen_symbols.add(key)
                entry_points.append(
                    {
                        "id": str(uuid4()),
                        "name": sym.name,
                        "type": sym.type,
                        "file_path": emb.file_path,
                        "line": sym.line,
                        "relevance_score": round(rrf_score, 4),
                    }
                )

    return {
        "query": query,
        "query_intent": intent.intent_type,
        "is_chinese": intent.is_chinese,
        "matched_concepts": intent.concepts[:10],
        "expanded_terms": intent.expanded_terms[:10],
        "search_strategy": {
            "primary": intent.search_strategy.primary,
            "secondary": intent.search_strategy.secondary,
        },
        "entry_points": entry_points[:5],
        "code_snippets": code_snippets,
        "recall_counts": {
            "vector": len(vector_hits),
            "symbol": len(symbol_hits),
            "bm25": len(bm25_hits),
            "sparse": len(sparse_hits),
            "fused": len(fused),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end retrieval test without writing to the database."
    )
    parser.add_argument(
        "path",
        help="Path to a source file or a directory to recursively index (Java/C/Python/...).",
    )
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Search query (can be given multiple times).",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use a mock LLM router instead of calling a real online LLM "
        "(only for smoke testing the pipeline).",
    )
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible base URL. Falls back to LLM_BASE_URL env var.",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="API key for the LLM provider. Falls back to LLM_API_KEY env var.",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Model name, e.g. deepseek-chat. Falls back to LLM_MODEL env var.",
    )
    parser.add_argument(
        "--llm-provider-type",
        default="openai_compatible",
        help="Provider type used by LLMClient (default: openai_compatible).",
    )
    parser.add_argument(
        "--mock-embedder",
        action="store_true",
        help="Use a deterministic mock embedder instead of downloading BGE-M3 "
        "(validates pipeline logic only, not semantic quality).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of final results to return per query.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON instead of a readable report.",
    )
    return parser.parse_args()


def _build_router(args: argparse.Namespace):
    if args.mock_llm:
        return MockLLMRouter()

    base_url = args.llm_base_url or os.environ.get("LLM_BASE_URL")
    api_key = args.llm_api_key or os.environ.get("LLM_API_KEY")
    model = args.llm_model or os.environ.get("LLM_MODEL")
    if not all([base_url, api_key, model]):
        raise SystemExit(
            "Real LLM is required by default. Provide --llm-base-url, --llm-api-key and --llm-model "
            "(or LLM_BASE_URL, LLM_API_KEY, LLM_MODEL env vars), or use --mock-llm."
        )
    return LocalLLMRouter(base_url, api_key, model, args.llm_provider_type)


def _collect_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return list_source_files(target)
    raise SystemExit(f"Path does not exist: {target}")


def main() -> None:
    args = _parse_args()

    target_path = Path(args.path)
    files = _collect_files(target_path)
    if not files:
        raise SystemExit(f"No parseable source files found under {target_path}")

    router = _build_router(args)
    embedder: Embedder = MockEmbedder() if args.mock_embedder else Embedder()

    if args.mock_llm:
        logger.warning("Using MOCK LLM router; Chinese enrichment will not reflect real LLM output.")
    if args.mock_embedder:
        logger.warning("Using MOCK embedder; vector/sparse scores are synthetic.")
    logger.info("Indexing %d source file(s) in memory (no DB writes)...", len(files))

    embeddings: List[MemEmbedding] = []
    symbols: List[MemSymbol] = []
    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
            file_embeddings, file_symbols = _index_file_in_memory(
                str(file_path), content, router, embedder
            )
            embeddings.extend(file_embeddings)
            symbols.extend(file_symbols)
        except Exception as exc:
            logger.warning("Skipping %s: %s", file_path, exc)
            continue

    logger.info("Memory index ready: %d embeddings, %d symbols", len(embeddings), len(symbols))

    results = []
    for query in args.query:
        result = _run_query(query, embeddings, symbols, embedder, router)
        results.append(result)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for result in results:
        print("=" * 80)
        print(f"Query : {result['query']}")
        print(f"Intent: {result['query_intent']}  |  Chinese: {result['is_chinese']}")
        print(f"Concepts: {', '.join(result['matched_concepts'])}")
        print(f"Expanded: {', '.join(result['expanded_terms'])}")
        print(f"Strategy: {result['search_strategy']['primary']} + {result['search_strategy']['secondary']}")
        print(f"Recall counts: {result['recall_counts']}")
        print("-" * 80)
        print("Entry points:")
        for ep in result["entry_points"]:
            print(f"  - {ep['name']} ({ep['type']}) @ {ep['file_path']}:{ep['line']}  score={ep['relevance_score']}")
        print("-" * 80)
        print("Top snippets:")
        for rank, snippet in enumerate(result["code_snippets"][: args.top_k], start=1):
            print(
                f"\n#{rank} {snippet['file_path']}:{snippet['line']} "
                f"score={snippet['score']} breakdown={snippet['score_breakdown']}"
            )
            print(snippet["content"].replace("\n", "\n    "))
        print()


if __name__ == "__main__":
    main()
