"""Hybrid search engine with intent-aware retrieval."""

import collections
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from models import CallGraphEdge, CodeFile, Embedding, SparseEmbedding, Symbol, SymbolFlowLabel
from schemas import SearchResultItem
from services.embedder import Embedder
from services.llm_router import LLMRouter
from services.llm_settings_service import get_effective_settings
from services.query_intent import QueryIntentAnalyzer, SearchStrategy, get_intent_analyzer
from services.query_normalizer import SymbolNormalizer
from services.reranker import CodeReranker, M3Reranker, get_m3_reranker

logger = logging.getLogger(__name__)

WEIGHT_VECTOR = 0.4
WEIGHT_SYMBOL = 0.3
WEIGHT_BM25 = 0.2
WEIGHT_GRAPH = 0.1
BONUS_VECTOR_SYMBOL = 0.1

RRF_K = 60

MAX_CHUNKS_PER_FILE = 3


@dataclass
class _Hit:
    result_id: UUID
    file_id: UUID
    repo_id: UUID
    repo_name: str
    file_path: str
    language: str
    content: str
    line: int
    vector_score: float = 0.0
    symbol_score: float = 0.0
    bm25_score: float = 0.0
    graph_score: float = 0.0
    sparse_score: float = 0.0
    sources: set = field(default_factory=set)
    symbol_id: Optional[UUID] = None
    symbol_name: Optional[str] = None
    rrf_score: float = 0.0


@dataclass
class SearchPathSnapshot:
    """A single retrieval path's intermediate results for debugging."""

    name: str
    enabled: bool
    top_k: int
    latency_ms: int
    hit_count: int
    hits: List[Dict[str, Any]]


@dataclass
class SearchTrace:
    """Container for the full retrieval pipeline trace.

    Passed through :meth:`Searcher._search_and_fuse`; when ``None`` the
    pipeline behaves exactly like before.
    """

    query_analysis: Dict[str, Any] = field(default_factory=dict)
    paths: List[SearchPathSnapshot] = field(default_factory=list)
    fusion: Dict[str, Any] = field(default_factory=dict)
    rerank: Dict[str, Any] = field(default_factory=dict)
    final_context: Optional[Any] = None

    def add_path(
        self,
        name: str,
        enabled: bool,
        top_k: int,
        latency_ms: int,
        hits: List[_Hit],
    ) -> None:
        self.paths.append(
            SearchPathSnapshot(
                name=name,
                enabled=enabled,
                top_k=top_k,
                latency_ms=latency_ms,
                hit_count=len(hits),
                hits=[self._hit_to_debug_dict(h, name) for h in hits],
            )
        )

    @staticmethod
    def _hit_to_debug_dict(hit: _Hit, source_name: str) -> Dict[str, Any]:
        score_attr = f"{source_name}_score"
        score = getattr(hit, score_attr, 0.0) if source_name != "symbol" else hit.symbol_score
        if source_name == "vector":
            score = hit.vector_score
        elif source_name == "sparse":
            score = hit.sparse_score
        elif source_name == "symbol":
            score = hit.symbol_score
        elif source_name == "bm25":
            score = hit.bm25_score
        elif source_name == "graph":
            score = hit.graph_score
        return {
            "id": str(hit.result_id),
            "file_path": hit.file_path,
            "line": hit.line,
            "language": hit.language,
            "content": hit.content[:400],
            "score": round(float(score), 4),
            "symbol_name": hit.symbol_name,
            "sources": sorted(hit.sources),
        }

    def set_fusion(self, rrf_k: int, hits: List[_Hit]) -> None:
        self.fusion = {
            "rrf_k": rrf_k,
            "hit_count": len(hits),
            "hits": [
                {
                    "id": str(h.result_id),
                    "file_path": h.file_path,
                    "line": h.line,
                    "rrf_score": round(float(h.rrf_score), 4),
                    "vector_score": round(float(h.vector_score), 4),
                    "symbol_score": round(float(h.symbol_score), 4),
                    "bm25_score": round(float(h.bm25_score), 4),
                    "sparse_score": round(float(h.sparse_score), 4),
                    "graph_score": round(float(h.graph_score), 4),
                    "sources": sorted(h.sources),
                }
                for h in hits
            ],
        }

    def set_rerank(
        self,
        code_reranker_input_count: int,
        code_reranker_output: List[SearchResultItem],
        m3_reranker_input_count: int,
        m3_reranker_output: List[SearchResultItem],
    ) -> None:
        self.rerank = {
            "code_reranker": {
                "input_count": code_reranker_input_count,
                "output_count": len(code_reranker_output),
                "output": [self._schema_to_debug_dict(s) for s in code_reranker_output],
            },
            "m3_reranker": {
                "input_count": m3_reranker_input_count,
                "output_count": len(m3_reranker_output),
                "output": [self._schema_to_debug_dict(s) for s in m3_reranker_output],
            },
        }

    @staticmethod
    def _schema_to_debug_dict(item: SearchResultItem) -> Dict[str, Any]:
        return {
            "id": str(item.id),
            "file_path": item.file_path,
            "line": item.line,
            "score": round(float(item.score), 4),
            "score_breakdown": item.score_breakdown,
            "file_role": getattr(item, "file_role", "other"),
        }


def _combined_score(hit: _Hit) -> float:
    """Compute the weighted combined score used for ranking and tie-breaking."""
    score = (
        WEIGHT_VECTOR * hit.vector_score
        + WEIGHT_SYMBOL * hit.symbol_score
        + WEIGHT_BM25 * hit.bm25_score
        + WEIGHT_GRAPH * hit.graph_score
        + hit.sparse_score * 0.1
    )
    if "vector" in hit.sources and "symbol" in hit.sources:
        score += BONUS_VECTOR_SYMBOL
    return score


def _choose_representative_hit(current: _Hit, candidate: _Hit) -> _Hit:
    """Keep the most informative hit for a given (file, line) location.

    Symbol information is critical because CallGraph relies on hit.symbol_id.
    When both hits have (or lack) symbol info, fall back to the combined score.
    """
    has_current_symbol = bool(current.symbol_id)
    has_candidate_symbol = bool(candidate.symbol_id)
    if has_candidate_symbol and not has_current_symbol:
        return candidate
    if has_current_symbol and not has_candidate_symbol:
        return current
    return candidate if _combined_score(candidate) > _combined_score(current) else current


def _dedup_source_hits(hits: List[_Hit], source: str) -> List[_Hit]:
    """Deduplicate hits within one source by (file_id, line) and sort by score."""
    by_key: Dict[tuple, _Hit] = {}
    score_attr = f"{source}_score"
    for hit in hits:
        key = (hit.file_id, hit.line)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = hit
            continue
        # Preserve symbol metadata even if the higher-scored hit lacks it.
        if hit.symbol_id and not existing.symbol_id:
            existing.symbol_id = hit.symbol_id
            existing.symbol_name = hit.symbol_name
        existing.sources.update(hit.sources)
        candidate_score = getattr(hit, score_attr, 0.0)
        if candidate_score > getattr(existing, score_attr, 0.0):
            setattr(existing, score_attr, candidate_score)
    return sorted(by_key.values(), key=lambda h: getattr(h, score_attr, 0.0), reverse=True)


def _rrf_fuse(results_by_source: Dict[str, List[_Hit]]) -> List[_Hit]:
    rrf_scores = collections.defaultdict(float)
    hit_by_key: Dict[tuple, _Hit] = {}

    for source_name, hits in results_by_source.items():
        for rank, hit in enumerate(hits, start=1):
            key = (hit.file_id, hit.line)
            rrf_scores[key] += 1.0 / (RRF_K + rank)
            if key not in hit_by_key:
                hit_by_key[key] = hit
            else:
                hit_by_key[key] = _choose_representative_hit(hit_by_key[key], hit)

    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: -rrf_scores[k])

    merged = []
    for key in sorted_keys:
        hit = hit_by_key[key]
        hit.rrf_score = rrf_scores[key]
        merged.append(hit)

    return merged


def _symbol_to_hit(symbol: Symbol, embeddings: List[Embedding]) -> _Hit:
    repo_name = symbol.repo.name if symbol.repo else ""
    for emb in embeddings:
        if emb.start_line <= symbol.line <= emb.end_line:
            return _Hit(
                result_id=emb.id,
                file_id=symbol.file_id,
                repo_id=symbol.repo_id,
                repo_name=repo_name,
                file_path=symbol.file.path,
                language=symbol.file.language,
                content=emb.content,
                line=symbol.line,
                symbol_score=1.0,
                sources={"symbol"},
                symbol_id=symbol.id,
                symbol_name=symbol.name,
            )
    return _Hit(
        result_id=symbol.id,
        file_id=symbol.file_id,
        repo_id=symbol.repo_id,
        repo_name=repo_name,
        file_path=symbol.file.path,
        language=symbol.file.language,
        content=f"{symbol.type} {symbol.name}",
        line=symbol.line,
        symbol_score=1.0,
        sources={"symbol"},
        symbol_id=symbol.id,
        symbol_name=symbol.name,
    )


class Searcher:
    """Intent-aware hybrid code search."""

    def __init__(self, db: Session):
        self.db = db
        self.embedder = Embedder()
        self.embedding_repo = EmbeddingRepository(db)
        self.symbol_repo = SymbolRepository(db)
        self.intent_analyzer = get_intent_analyzer()

    def search_with_context(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
        intent=None,
        path_overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[SearchTrace] = None,
    ) -> "CodeContext":
        from schemas import CallChain, CodeContext, FileSummary, SymbolEntry

        llm_settings = get_effective_settings(self.db, repo_id)
        enable_query_llm_expand = llm_settings.get("enable_query_llm_expand", True)
        llm_router = LLMRouter(self.db) if enable_query_llm_expand else None

        if intent is None:
            intent = self.intent_analyzer.analyze(
                query,
                repo_id=str(repo_id) if repo_id else None,
                db=self.db,
                enable_llm_expand=enable_query_llm_expand,
                llm_router=llm_router,
            )
        logger.info("Query intent: %s, strategy: %s", intent.intent_type, intent.search_strategy)

        strategy = intent.search_strategy
        hits = self._search_and_fuse(
            query, repo_id, limit,
            search_terms=intent.expanded_terms,
            path_overrides=path_overrides,
            trace=trace,
        )

        entry_points = []
        call_chain = None
        related_files = []
        code_snippets = []

        seen_symbols = set()
        for hit in hits[:5]:
            if hit.symbol_id and hit.symbol_id not in seen_symbols:
                seen_symbols.add(hit.symbol_id)
                sym = self.db.query(Symbol).filter(Symbol.id == hit.symbol_id).first()
                if sym:
                    entry_point = self._symbol_entry_with_label(sym)
                    entry_point.relevance_score = _combined_score(hit)
                    entry_points.append(entry_point)

        if strategy.include_callers or strategy.include_callees:
            if entry_points:
                root_symbol_id = UUID(entry_points[0].id)
                chain = self._build_call_chain(
                    root_symbol_id,
                    strategy.call_depth,
                    strategy.include_callers,
                    strategy.include_callees,
                )
                call_chain = chain
                chain.flow_summary = self._generate_flow_summary(query, intent.intent_type, entry_points, chain)
                chain_files = self._collect_chain_files(chain)
                related_files.extend(chain_files)

        flow_summary = call_chain.flow_summary if call_chain else None

        file_chunk_count: Dict[str, int] = {}
        for hit in hits:
            if len(code_snippets) >= limit:
                break
            cnt = file_chunk_count.get(hit.file_path, 0)
            if cnt >= MAX_CHUNKS_PER_FILE:
                continue
            file_chunk_count[hit.file_path] = cnt + 1
            code_snippets.append(SearchResultItem(
                id=hit.result_id,
                file_id=hit.file_id,
                repo_id=hit.repo_id,
                repo_name=hit.repo_name,
                file_path=hit.file_path,
                language=hit.language,
                content=hit.content,
                line=hit.line,
                score=self._final_score(hit),
                score_breakdown={
                    "vector": round(hit.vector_score, 4),
                    "symbol": round(hit.symbol_score, 4),
                    "bm25": round(hit.bm25_score, 4),
                    "graph": round(hit.graph_score, 4),
                    "sparse": round(hit.sparse_score, 4),
                    "rrf": round(hit.rrf_score, 4),
                    "final": round(self._final_score(hit), 4),
                },
                file_role=self._infer_file_role(hit.file_path),
            ))

        if not related_files:
            for snippet in code_snippets[:8]:
                role = self._infer_file_role(snippet.file_path)
                related_files.append(FileSummary(
                    path=snippet.file_path,
                    role=role,
                    relevance_score=snippet.score,
                    key_symbols=[s.name for s in entry_points if s.file_path == snippet.file_path],
                ))

        return CodeContext(
            query=query,
            query_intent=intent.intent_type,
            matched_concepts=intent.expanded_terms[:10],
            entry_points=entry_points,
            call_chain=call_chain,
            flow_summary=flow_summary,
            related_files=related_files,
            code_snippets=code_snippets,
            total_files=len(related_files),
            total_symbols=len(entry_points),
            search_latency_ms=0,
        )

    def _symbol_entry_with_label(self, sym: Symbol) -> "SymbolEntry":
        from schemas import SymbolEntry

        label = (
            self.db.query(SymbolFlowLabel)
            .filter(SymbolFlowLabel.symbol_id == sym.id)
            .first()
        )
        return SymbolEntry(
            id=str(sym.id),
            name=sym.name,
            type=sym.type,
            file_path=sym.file.path if sym.file else "",
            line=sym.line,
            layer=label.layer if label else None,
            module=label.module if label else None,
            chinese_name=label.chinese_name if label else None,
            io_description=label.io_description if label else None,
        )

    def _generate_flow_summary(
        self,
        query: str,
        intent_type: str,
        entry_points: List["SymbolEntry"],
        chain: "CallChain",
    ) -> Optional[str]:
        """Generate a concise Chinese description of the code flow for how_it_works queries."""
        if intent_type != "how_it_works":
            return None
        if not chain or not chain.root:
            return None

        root_name = chain.root.chinese_name or chain.root.name
        parts = [f"「{query}」对应入口为 {root_name}（{chain.root.layer or '未知层'}）。"]

        if chain.upstream:
            names = [s.chinese_name or s.name for s in chain.upstream[:5]]
            parts.append(f"上游调用：{', '.join(names)}。")
        if chain.downstream:
            names = [s.chinese_name or s.name for s in chain.downstream[:5]]
            parts.append(f"下游处理：{', '.join(names)}。")

        return "".join(parts)

    def _build_call_chain(
        self,
        root_symbol_id: UUID,
        depth: int,
        include_callers: bool,
        include_callees: bool,
    ) -> "CallChain":
        from schemas import CallChain, SymbolEntry

        root = self.db.query(Symbol).filter(Symbol.id == root_symbol_id).first()
        if not root:
            return CallChain(
                root=SymbolEntry(id=str(root_symbol_id), name="", type="", file_path="", line=0),
                upstream=[], downstream=[], depth=0,
            )

        root_entry = self._symbol_entry_with_label(root)

        upstream = []
        downstream = []

        if include_callers:
            caller_ids = self._query_callers(root_symbol_id, depth)
            for cid in caller_ids:
                sym = self.db.query(Symbol).filter(Symbol.id == cid).first()
                if sym:
                    upstream.append(self._symbol_entry_with_label(sym))

        if include_callees:
            callee_ids = self._query_callees(root_symbol_id, depth)
            for cid in callee_ids:
                sym = self.db.query(Symbol).filter(Symbol.id == cid).first()
                if sym:
                    downstream.append(self._symbol_entry_with_label(sym))

        return CallChain(
            root=root_entry,
            upstream=upstream,
            downstream=downstream,
            depth=depth,
        )

    def _query_callers(self, symbol_id: UUID, depth: int) -> List[UUID]:
        results = []
        current = {symbol_id}
        visited = {symbol_id}

        for _ in range(depth):
            next_level = set()
            for sid in current:
                edges = self.db.query(CallGraphEdge).filter(
                    CallGraphEdge.target_symbol_id == sid
                ).all()
                for edge in edges:
                    if edge.source_symbol_id not in visited:
                        visited.add(edge.source_symbol_id)
                        next_level.add(edge.source_symbol_id)
                        results.append(edge.source_symbol_id)
            current = next_level
            if not current:
                break

        return results

    def _query_callees(self, symbol_id: UUID, depth: int) -> List[UUID]:
        results = []
        current = {symbol_id}
        visited = {symbol_id}

        for _ in range(depth):
            next_level = set()
            for sid in current:
                edges = self.db.query(CallGraphEdge).filter(
                    CallGraphEdge.source_symbol_id == sid
                ).all()
                for edge in edges:
                    if edge.target_symbol_id not in visited:
                        visited.add(edge.target_symbol_id)
                        next_level.add(edge.target_symbol_id)
                        results.append(edge.target_symbol_id)
            current = next_level
            if not current:
                break

        return results

    def _graph_search_from_symbol(
        self,
        symbol_id: UUID,
        repo_id: Optional[UUID],
        depth: int,
    ) -> List[_Hit]:
        related_ids = set()
        related_ids.update(self._query_callers(symbol_id, depth))
        related_ids.update(self._query_callees(symbol_id, depth))

        if not related_ids:
            return []

        symbols = self.db.query(Symbol).filter(Symbol.id.in_(list(related_ids)))
        if repo_id:
            symbols = symbols.filter(Symbol.repo_id == repo_id)
        symbols = symbols.all()

        hits = []
        for sym in symbols:
            embeddings = self._file_embeddings(sym.file_id)
            hit = _symbol_to_hit(sym, embeddings)
            hit.graph_score = 0.7
            hit.sources.add("graph")
            hits.append(hit)

        return hits

    def _collect_chain_files(self, chain) -> List["FileSummary"]:
        from schemas import FileSummary

        file_scores: Dict[str, float] = {}
        file_symbols: Dict[str, List[str]] = {}

        for sym in [chain.root] + chain.upstream + chain.downstream:
            path = sym.file_path
            if path not in file_scores:
                file_scores[path] = 0.0
                file_symbols[path] = []
            file_scores[path] += 1.0
            file_symbols[path].append(sym.name)

        results = []
        for path, score in sorted(file_scores.items(), key=lambda x: -x[1]):
            role = self._infer_file_role(path)
            results.append(FileSummary(
                path=path,
                role=role,
                relevance_score=min(score / 5.0, 1.0),
                key_symbols=file_symbols.get(path, [])[:5],
            ))

        return results

    def _infer_file_role(self, file_path: str) -> str:
        """Infer the architectural role of a file from its path and name.

        The heuristic uses three signals, in order of reliability:
        1. Directory structure (e.g. services/, controllers/, data/)
        2. File name tokens (e.g. *adapter*, *service*)
        3. Language / framework conventions (e.g. .tsx in packages/web/)
        """
        path_lower = file_path.lower()
        parts = file_path.lower().split("/")
        name = parts[-1]
        name_no_ext = name.split(".")[0]

        # 1. Test files (strongest signal).
        if "test" in path_lower or "spec" in name or "__tests__" in path_lower:
            return "test"

        # 2. Web frontend files.
        if path_lower.startswith("packages/web/") or "/src/pages/" in path_lower or "/components/" in path_lower:
            if name.endswith((".tsx", ".jsx", ".vue", ".ts", ".js")):
                return "web"

        # 3. Directory-based role inference.
        dir_roles = {
            "api": "controller",
            "apis": "controller",
            "controllers": "controller",
            "routes": "controller",
            "handlers": "controller",
            "services": "service",
            "service": "service",
            "biz": "service",
            "business": "service",
            "indexer": "analyzer",
            "parser": "analyzer",
            "analyzer": "analyzer",
            "enricher": "analyzer",
            "repositories": "repository",
            "repository": "repository",
            "dao": "repository",
            "mapper": "repository",
            "data": "repository",
            "adapters": "adapter",
            "adapter": "adapter",
            "models": "model",
            "entities": "model",
            "entity": "model",
            "domain": "model",
            "dto": "model",
            "config": "config",
            "configs": "config",
            "settings": "config",
            "utils": "utility",
            "helpers": "utility",
            "common": "utility",
            "middleware": "middleware",
            "middlewares": "middleware",
            "interceptors": "middleware",
            "filters": "middleware",
        }
        for part in parts:
            if part in dir_roles:
                role = dir_roles[part]
                # Special case: files under data/ whose name contains adapter
                # are more precisely "adapter" than generic "repository".
                if role == "repository" and "adapter" in name_no_ext:
                    return "adapter"
                # Special case: files under services/ that implement analysis/
                # retrieval logic are more precisely "analyzer".
                if role == "service" and any(
                    token in name_no_ext
                    for token in ("searcher", "analyzer", "parser", "enricher", "indexer")
                ):
                    return "analyzer"
                return role

        # 4. Name-based role inference (fallback).
        name_tokens = {
            "controller": "controller",
            "handler": "controller",
            "route": "controller",
            "router": "controller",
            "service": "service",
            "biz": "service",
            "business": "service",
            "searcher": "analyzer",
            "analyzer": "analyzer",
            "parser": "analyzer",
            "enricher": "analyzer",
            "indexer": "analyzer",
            "repository": "repository",
            "dao": "repository",
            "mapper": "repository",
            "adapter": "adapter",
            "model": "model",
            "entity": "model",
            "domain": "model",
            "dto": "model",
            "config": "config",
            "settings": "config",
            "properties": "config",
            "util": "utility",
            "helper": "utility",
            "common": "utility",
            "middleware": "middleware",
            "interceptor": "middleware",
            "filter": "middleware",
        }
        for token, role in name_tokens.items():
            if token in name_no_ext:
                return role

        return "other"

    def _search_and_fuse(
        self,
        query: str,
        repo_id: Optional[UUID],
        limit: int,
        search_terms: Optional[List[str]] = None,
        path_overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[SearchTrace] = None,
    ) -> List[_Hit]:
        """Unified retrieval pipeline: vector + sparse + symbol + bm25 + graph,
        then RRF fusion and two-stage reranking.

        This is the shared core used by both ``hybrid_search`` and
        ``search_with_context`` so that intent-aware searches benefit from
        the same semantic-rerank quality.

        ``search_terms`` carries the expanded query terms (e.g. SEMANTIC_MAP
        English mappings such as 订单 -> order). They feed the symbol and
        BM25 paths so Chinese queries can match English code identifiers.

        ``path_overrides`` lets debug callers tune the pipeline per request
        without changing global constants. Expected keys: ``enabled`` (set of
        path names), ``top_k`` (path -> int). When absent all paths default
        to enabled with their standard top_k.

        ``trace`` collects intermediate results for the debug endpoint. When
        ``None`` the pipeline is byte-for-byte identical to the original path.
        """
        self.db.execute(text("SET hnsw.ef_search = 128"))

        overrides = path_overrides or {}
        enabled_paths: Set[str] = set(overrides.get("enabled", {
            "vector", "sparse", "symbol", "bm25", "graph",
        }))
        top_k_overrides: Dict[str, int] = overrides.get("top_k", {})

        def _top_k(name: str, default: int = 50) -> int:
            return top_k_overrides.get(name, default)

        def _run_path(name: str, runner) -> List[_Hit]:
            """Execute one retrieval path, honouring enabled_paths and tracing."""
            if name not in enabled_paths:
                if trace is not None:
                    trace.add_path(name, False, _top_k(name), 0, [])
                return []
            start = time.perf_counter()
            try:
                results = runner(_top_k(name))
            except Exception as e:
                logger.warning("%s search failed: %s", name, e)
                results = []
            latency_ms = int((time.perf_counter() - start) * 1000)
            if trace is not None:
                trace.add_path(name, True, _top_k(name), latency_ms, results)
            return results

        # Core retrieval paths: failures must propagate so the caller knows the
        # search could not be completed correctly.
        query_embedding = self.embedder.encode_query(query)
        vector_results = _run_path(
            "vector", lambda top_k: self._vector_search(query_embedding, repo_id, top_k=top_k)
        )

        symbol_results = _run_path(
            "symbol", lambda top_k: self._symbol_search_multi(query, search_terms, repo_id, top_k=top_k)
        )

        is_chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
        bm25_concepts = self.intent_analyzer._extract_concepts(query, is_chinese)
        for term in search_terms or []:
            if term != query and term not in bm25_concepts:
                bm25_concepts.append(term)
        bm25_results = _run_path(
            "bm25", lambda top_k: self._bm25_search(query, repo_id, top_k=top_k, concepts=bm25_concepts)
        )

        # Sparse and graph search are supplementary sources. If they fail, the
        # search can still continue with the core results above.
        def _sparse_runner(top_k: int) -> List[_Hit]:
            try:
                query_sparse = self.embedder.encode_query_sparse(query)
            except Exception as e:
                logger.warning("Sparse encoding failed: %s", e)
                return []
            if not query_sparse:
                return []
            return self._sparse_search(query_sparse, repo_id, top_k=top_k)

        sparse_results = _run_path("sparse", _sparse_runner)

        graph_results: List[_Hit] = []
        if "graph" in enabled_paths and symbol_results:
            try:
                graph_results = _run_path(
                    "graph", lambda top_k: self._graph_search(symbol_results, repo_id, top_k=top_k)
                )
            except Exception as e:
                logger.warning("Graph search skipped: %s", e)
        elif trace is not None:
            trace.add_path("graph", False, _top_k("graph"), 0, [])

        results_by_source = {
            "vector": vector_results,
            "sparse": sparse_results,
            "symbol": symbol_results,
            "bm25": bm25_results,
            "graph": graph_results,
        }
        hits = _rrf_fuse(results_by_source)
        if trace is not None:
            trace.set_fusion(RRF_K, hits)

        schema_results = [self._to_schema(hit) for hit in hits[:limit * 2]]
        reranked = CodeReranker().rerank(query, schema_results, search_terms=search_terms)

        m3_reranker = get_m3_reranker()
        final_schemas = m3_reranker.rerank(query, reranked[:limit * 2], top_k=limit)

        if trace is not None:
            trace.set_rerank(
                code_reranker_input_count=len(schema_results),
                code_reranker_output=reranked,
                m3_reranker_input_count=len(reranked),
                m3_reranker_output=final_schemas,
            )

        # Map reranked schemas back to _Hit objects so callers can still
        # access hit.symbol_id and other internal metadata.
        hit_by_id = {hit.result_id: hit for hit in hits}
        final_hits: List[_Hit] = []
        for schema in final_schemas:
            hit = hit_by_id.get(schema.id)
            if hit:
                final_hits.append(hit)
        return final_hits

    def debug_search(
        self,
        query: str,
        repo_id: UUID,
        limit: int = 20,
        path_overrides: Optional[Dict[str, Any]] = None,
        enable_llm_expand: bool = False,
    ) -> Tuple["CodeContext", SearchTrace]:
        """Run the full search pipeline and return both the final context
        and a complete trace of every retrieval / fusion / rerank stage.

        This is intended for the retrieval testing center UI. It reuses
        :meth:`search_with_context` so the final output is identical to what
        the MCP / chat endpoints receive.
        """
        llm_settings = get_effective_settings(self.db, repo_id)
        use_llm_expand = enable_llm_expand and llm_settings.get(
            "enable_query_llm_expand", True
        )
        llm_router = LLMRouter(self.db) if use_llm_expand else None

        intent = self.intent_analyzer.analyze(
            query,
            repo_id=str(repo_id),
            db=self.db,
            enable_llm_expand=use_llm_expand,
            llm_router=llm_router,
        )

        trace = SearchTrace()
        trace.query_analysis = {
            "intent_type": intent.intent_type,
            "is_chinese": bool(re.search(r"[\u4e00-\u9fff]", query)),
            "concepts": self.intent_analyzer._extract_concepts(
                query, bool(re.search(r"[\u4e00-\u9fff]", query))
            ),
            "expanded_terms": intent.expanded_terms,
        }

        context = self.search_with_context(
            query=query,
            repo_id=repo_id,
            limit=limit,
            intent=intent,
            path_overrides=path_overrides,
            trace=trace,
        )
        trace.final_context = context
        return context, trace

    def hybrid_search(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
    ) -> List[SearchResultItem]:
        logger.info("Hybrid search query=%s repo_id=%s", query, repo_id)
        # Analyze without LLM expansion (network call) so the hot path stays
        # fast; SEMANTIC_MAP / domain-synonym expansions still apply.
        intent = self.intent_analyzer.analyze(
            query,
            repo_id=str(repo_id) if repo_id else None,
            db=self.db,
            enable_llm_expand=False,
        )
        hits = self._search_and_fuse(query, repo_id, limit, search_terms=intent.expanded_terms)
        return [self._to_schema(hit) for hit in hits[:limit]]

    def symbol_search(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
    ) -> List[SearchResultItem]:
        symbols = self._symbol_search_raw(query, repo_id, limit * 3)
        hits = [_symbol_to_hit(s, self._file_embeddings(s.file_id)) for s in symbols]
        hits.sort(key=lambda h: h.symbol_score, reverse=True)
        return [self._to_schema(hit) for hit in hits[:limit]]

    def _vector_search(
        self,
        query_embedding: List[float],
        repo_id: Optional[UUID],
        top_k: int = 50,
        limit: int = 50,
    ) -> List[_Hit]:
        rows = self.embedding_repo.vector_search(query_embedding, repo_id, top_k)

        hits: List[_Hit] = []
        for row in rows:
            distance = row.get("distance")
            if isinstance(distance, str):
                distance = float(distance)
            score = max(0.0, 1.0 - distance)
            hits.append(
                _Hit(
                    result_id=row["embedding_id"],
                    file_id=row["file_id"],
                    repo_id=row["repo_id"],
                    repo_name=row["repo_name"],
                    file_path=row["file_path"],
                    language=row["language"],
                    content=row["content"],
                    line=row["start_line"],
                    vector_score=score,
                    sources={"vector"},
                )
            )
        return hits

    def _symbol_search_raw(
        self,
        query: str,
        repo_id: Optional[UUID],
        limit: int = 50,
    ) -> List[Symbol]:
        return self.symbol_repo.search_by_name(query, repo_id, limit)

    def _symbol_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        symbols = self._symbol_search_raw(query, repo_id, top_k)
        hits: List[_Hit] = []
        for sym in symbols:
            embeddings = self._file_embeddings(sym.file_id)
            hit = _symbol_to_hit(sym, embeddings)
            preset_score = getattr(sym, "_search_score", None)
            if preset_score is not None:
                # Score comes from SymbolRepository (e.g. Chinese flow-label match).
                hit.symbol_score = preset_score
            elif SymbolNormalizer.match(query, sym.name):
                if SymbolNormalizer.normalize(query) == SymbolNormalizer.normalize(sym.name):
                    hit.symbol_score = 1.0
                elif SymbolNormalizer.normalize(query) in SymbolNormalizer.normalize(sym.name):
                    hit.symbol_score = 0.9
                else:
                    hit.symbol_score = 0.7
            else:
                hit.symbol_score = 0.5
            hits.append(hit)
        return hits

    def _symbol_search_multi(
        self,
        query: str,
        search_terms: Optional[List[str]],
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        """Symbol search over the raw query plus expanded terms.

        A Chinese query like ``订单创建流程`` never matches an English symbol
        name directly; the expanded terms (SEMANTIC_MAP mappings such as
        ``订单 -> order``) let us find symbols like ``createOrder``. Results
        are merged by symbol, keeping the highest score, so duplicates from
        overlapping terms do not inflate the RRF input.
        """
        terms: List[str] = [query]
        for term in search_terms or []:
            if len(terms) >= 10:  # cap fan-out to bound DB work
                break
            if term != query and len(term) >= 2:
                terms.append(term)

        best: Dict[UUID, _Hit] = {}
        for term in terms:
            for hit in self._symbol_search(term, repo_id, top_k):
                key = hit.symbol_id or hit.result_id
                existing = best.get(key)
                if existing is None or hit.symbol_score > existing.symbol_score:
                    best[key] = hit
        return sorted(best.values(), key=lambda h: h.symbol_score, reverse=True)[:top_k]

    def _bm25_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        top_k: int = 50,
        concepts: Optional[List[str]] = None,
    ) -> List[_Hit]:
        like_clauses: List[str] = []
        params: Dict[str, Any] = {
            "query": query,
            "repo_id": str(repo_id) if repo_id else None,
            "limit": top_k,
        }

        # Direct phrase match bonus.
        params["query_like"] = f"%{query}%"
        for attr in ("e.content", "ee.chinese_summary", "ee.keywords"):
            like_clauses.append(f"{attr} ILIKE :query_like")

        # Concept-level fuzzy fallback for Chinese and short terms.
        for idx, concept in enumerate(concepts or []):
            if len(concept) < 2:
                continue
            key = f"concept_{idx}_like"
            params[key] = f"%{concept}%"
            like_clauses.append(f"ee.chinese_summary ILIKE :{key}")
            like_clauses.append(f"ee.keywords ILIKE :{key}")
            like_clauses.append(f"e.content ILIKE :{key}")

        concept_where = " OR ".join(like_clauses) if like_clauses else "FALSE"

        sql = text(
            f"""
            SELECT e.id AS embedding_id,
                   e.file_id,
                   e.repo_id,
                   r.name AS repo_name,
                   e.content,
                   e.start_line,
                   e.end_line,
                   f.path AS file_path,
                   f.language,
                   GREATEST(
                       ts_rank_cd(to_tsvector('english', e.content), plainto_tsquery('english', :query)),
                       ts_rank_cd(to_tsvector('simple', e.content), plainto_tsquery('simple', :query)),
                       COALESCE(ts_rank_cd(to_tsvector('simple', ee.chinese_summary), plainto_tsquery('simple', :query)), 0),
                       COALESCE(ts_rank_cd(to_tsvector('simple', ee.keywords), plainto_tsquery('simple', :query)), 0),
                       CASE WHEN e.content ILIKE :query_like THEN 0.2 ELSE 0 END,
                       CASE WHEN ee.chinese_summary ILIKE :query_like THEN 0.6 ELSE 0 END,
                       CASE WHEN ee.keywords ILIKE :query_like THEN 0.9 ELSE 0 END
                   ) AS rank
            FROM embeddings e
            JOIN code_files f ON f.id = e.file_id
            JOIN repositories r ON r.id = e.repo_id
            LEFT JOIN embedding_enrichments ee ON ee.embedding_id = e.id
            WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
              AND (
                  to_tsvector('english', e.content) @@ plainto_tsquery('english', :query)
                  OR to_tsvector('simple', e.content) @@ plainto_tsquery('simple', :query)
                  OR to_tsvector('simple', ee.chinese_summary) @@ plainto_tsquery('simple', :query)
                  OR to_tsvector('simple', ee.keywords) @@ plainto_tsquery('simple', :query)
                  OR {concept_where}
              )
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            sql,
            params,
        ).fetchall()

        hits: List[_Hit] = []
        for row in rows:
            rank = row.rank
            if isinstance(rank, str):
                rank = float(rank)
            hits.append(
                _Hit(
                    result_id=row.embedding_id,
                    file_id=row.file_id,
                    repo_id=row.repo_id,
                    repo_name=row.repo_name,
                    file_path=row.file_path,
                    language=row.language,
                    content=row.content,
                    line=row.start_line,
                    bm25_score=rank,
                    sources={"bm25"},
                )
            )
        return hits

    def _graph_search(
        self,
        symbol_hits: List[_Hit],
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        if not symbol_hits:
            return []

        symbol_ids = [h.symbol_id for h in symbol_hits if h.symbol_id and h.sources == {"symbol"}]
        if symbol_ids:
            related_symbols = self.symbol_repo.get_related_by_edges(symbol_ids, top_k)
        else:
            file_ids = list({h.file_id for h in symbol_hits})
            related_symbols = self.symbol_repo.get_by_file_ids(file_ids, top_k)

        hits: List[_Hit] = []
        for sym in related_symbols:
            embeddings = self._file_embeddings(sym.file_id)
            hit = _symbol_to_hit(sym, embeddings)
            hit.graph_score = 0.7
            hit.sources.add("graph")
            hits.append(hit)
        return hits

    def _file_embeddings(self, file_id: UUID) -> List[Embedding]:
        return self.embedding_repo.get_by_file_id(file_id)

    def _sparse_search(
        self,
        query_sparse: Dict[int, float],
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        if not query_sparse:
            return []

        query_tokens = list(query_sparse.keys())

        rows = self.db.query(
            SparseEmbedding.embedding_id,
            SparseEmbedding.token_id,
            SparseEmbedding.weight,
        ).filter(
            SparseEmbedding.token_id.in_(query_tokens),
        )

        if repo_id:
            rows = rows.join(
                Embedding,
                Embedding.id == SparseEmbedding.embedding_id,
            ).filter(Embedding.repo_id == repo_id)

        rows = rows.all()

        scores = {}
        for row in rows:
            eid = row.embedding_id
            tid = row.token_id
            doc_weight = row.weight
            query_weight = query_sparse.get(tid, 0)

            if eid not in scores:
                scores[eid] = 0
            scores[eid] += query_weight * doc_weight

        sorted_eids = sorted(scores.keys(), key=lambda eid: -scores[eid])[:top_k]

        embeddings = self.db.query(Embedding).filter(
            Embedding.id.in_(sorted_eids)
        ).all()

        hits = []
        for emb in embeddings:
            score = scores.get(emb.id, 0)
            hits.append(_Hit(
                result_id=emb.id,
                file_id=emb.file_id,
                repo_id=emb.repo_id,
                repo_name=emb.repo.name if emb.repo else "",
                file_path=emb.file.path if emb.file else "",
                language=emb.file.language if emb.file else "",
                content=emb.content,
                line=emb.start_line,
                sparse_score=score,
                sources={"sparse"},
            ))
        return hits

    def _final_score(self, hit: _Hit) -> float:
        return _combined_score(hit)

    def _to_schema(self, hit: _Hit) -> SearchResultItem:
        final_score = getattr(hit, 'rrf_score', self._final_score(hit))
        return SearchResultItem(
            id=hit.result_id,
            file_id=hit.file_id,
            repo_id=hit.repo_id,
            repo_name=hit.repo_name,
            file_path=hit.file_path,
            language=hit.language,
            content=hit.content,
            line=hit.line,
            score=final_score,
            score_breakdown={
                "vector": round(hit.vector_score, 4),
                "symbol": round(hit.symbol_score, 4),
                "bm25": round(hit.bm25_score, 4),
                "graph": round(hit.graph_score, 4),
                "sparse": round(hit.sparse_score, 4),
                "rrf": round(getattr(hit, 'rrf_score', 0), 4),
                "final": round(final_score, 4),
            },
            file_role=self._infer_file_role(hit.file_path),
        )


from repositories import EmbeddingRepository, SymbolRepository