"""Hybrid search engine with intent-aware retrieval."""

import collections
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from config import settings
from models import CallGraphEdge, CodeFile, Embedding, FrameworkRoute, Repository, SparseEmbedding, Symbol, SymbolFlowLabel
from schemas import SearchResultItem
from services.embedder import Embedder
from services.llm_router import LLMRouter
from services.llm_settings_service import get_effective_settings
from services.query_intent import QueryIntentAnalyzer, SearchStrategy, get_intent_analyzer
from services.query_normalizer import SymbolNormalizer
from services.reranker import ROLE_WEIGHTS, CodeReranker, M3Reranker, get_m3_reranker

logger = logging.getLogger(__name__)

WEIGHT_VECTOR = 0.4
WEIGHT_SYMBOL = 0.3
WEIGHT_BM25 = 0.2
WEIGHT_GRAPH = 0.1
BONUS_VECTOR_SYMBOL = 0.1

RRF_K = 60

MAX_CHUNKS_PER_FILE = 3

# 向量相似度阈值：BGE-M3 编码下，与代码库相关的查询向量分数通常 ≥0.5
# （实测「登录流程」0.535~0.637），无关查询（如「火星撞地球」）仅 0.39~0.43。
# 低于阈值的向量命中直接丢弃，避免无意义查询也返回 top-k 结果。
VECTOR_SIMILARITY_THRESHOLD = 0.5

# 稀疏命中分数阈值：无关查询的 token 权重乘积趋近于 0（实测 0.0055），
# 相关命中通常 ≥0.04。过滤掉噪声级命中。
SPARSE_SCORE_THRESHOLD = 0.01

# 静态/构建产物/第三方目录路径。这些目录的压缩产物（如 layui/minified JS）
# 会被符号解析器拆出大量单字符符号（如 `s`）并进入调用图，混入调用链后
# 会显示成「一堆单独的英文字母」。所有下游展示（调用链/入口点/向量命中）
# 都应排除这类路径。
STATIC_PATH_RE = re.compile(r"(^|/)(static|assets|dist|public|build|vendor|libs|node_modules)(/|$)")

# 符号名完全等于这些通用词时视为框架/工具函数（HTTP 方法封装、通用 CRUD
# 命名，如 web/api.js 的 `post()`）。它们不反映业务语义，且会与查询扩展的
# 泛化词（帖子→post）撞车，造成跨项目符号级误命中，因此不参与符号检索。
GENERIC_SYMBOL_NAMES = frozenset({
    "post", "get", "put", "delete", "patch", "head", "options",
    "create", "update", "query", "list", "search", "find", "save",
    "remove", "del", "add", "edit", "index", "init", "run", "main",
})


def _is_confident_hit(hit: "_Hit") -> bool:
    """判定一条融合命中是否有足够的召回证据，过滤跨项目误命中。

    独有功能查询（如「帖子点赞怎么实现」）在无关仓库里往往只有 vector
    一条弱路径命中（实测 0.53~0.57 的泛匹配，无 symbol/bm25/graph 支撑），
    但也能通过 0.5 的向量阈值进入融合。真实相关查询则通常多路重合
    （vector + bm25 + symbol + sparse）。规则：

    - 多路召回（≥2 路）：需要至少一路达到强命中门槛（多路全弱证据的
      词级巧合（task/job/login）不视为真实相关）
    - 单路召回：需要该路分数足够强才保留（阈值取「无关仓库泛匹配」与
      「同仓库相关命中」之间的空隙）
    """
    sources = hit.sources
    if len(sources) >= 2:
        # 多路召回但全是弱证据（如 vector 0.54 + bm25 0.2 + sparse 0.05，
        # 常见于通用英文词 task/job/login 的跨项目词级巧合）仍应过滤，
        # 要求至少一路达到强命中门槛。
        strong = (
            hit.vector_score >= 0.58
            or hit.bm25_score >= 0.4
            or hit.symbol_score >= 0.8
            or hit.sparse_score >= 0.1
            or hit.graph_score >= 0.05
        )
        return strong
    if sources == {"vector"}:
        return hit.vector_score >= 0.58
    if sources == {"bm25"}:
        return hit.bm25_score >= 0.4
    if sources == {"symbol"}:
        return hit.symbol_score >= 0.8
    if sources == {"sparse"}:
        return hit.sparse_score >= 0.1
    if sources == {"graph"}:
        return hit.graph_score >= 0.05
    return True


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
    score: float = 0.0
    is_override: bool = False
    branch: Optional[str] = None


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
                branch=symbol.branch,
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
        branch=symbol.branch,
    )


class Searcher:
    """Intent-aware hybrid code search."""

    def __init__(self, db: Session):
        self.db = db
        self.embedder = Embedder()
        self.embedding_repo = EmbeddingRepository(db)
        self.symbol_repo = SymbolRepository(db)
        self.intent_analyzer = get_intent_analyzer()

    def _resolve_branch(self, repo_id: Optional[UUID], branch: str) -> Tuple[str, bool]:
        """Resolve requested branch to an actual indexed branch with fallback.

        Returns (actual_branch, branch_fallback).
        """
        if not repo_id:
            # 全局搜索跨仓库，各仓库 default_branch 可能不同，分支过滤无意义；
            # 返回 None 表示所有检索路径不做分支过滤。
            return None, False
        repo = self.db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            return branch, False
        default_branch = repo.default_branch or "main"
        if branch == default_branch:
            return branch, False
        active_branches = json.loads(repo.active_branches or "[]") or [default_branch]
        if branch in active_branches:
            # If branch has no indexed files yet, fallback to default_branch
            has_branch_files = (
                self.db.query(CodeFile.id)
                .filter(CodeFile.repo_id == repo_id, CodeFile.branch == branch)
                .first()
                is not None
            )
            if has_branch_files:
                return branch, False
        return default_branch, True

    def search_with_context(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        branch: str = "main",
        limit: int = 20,
        intent=None,
        path_overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[SearchTrace] = None,
    ) -> "CodeContext":
        from schemas import CallChain, CodeContext, FileSummary, SearchMeta, SymbolEntry

        _phase_t0 = time.perf_counter()

        def _phase_log(name: str) -> None:
            nonlocal _phase_t0
            logger.info(
                "PHASE %-20s took %4.0fms",
                name,
                (time.perf_counter() - _phase_t0) * 1000,
            )
            _phase_t0 = time.perf_counter()

        llm_settings = get_effective_settings(self.db, repo_id)
        # 在线 LLM 查询扩展主开关（默认开启）：开启后 query 扩展会追加
        # LLM 生成的中文同义词/英文代码词；关闭或 LLM 不可用时自动回落到
        # QueryIntentAnalyzer 的本地模板层（SEMANTIC_MAP/领域同义词）兜底。
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
        _phase_log("intent_analyze")

        requested_branch = branch
        actual_branch, branch_fallback = self._resolve_branch(repo_id, branch)

        strategy = intent.search_strategy
        hits = self._search_and_fuse(
            query, repo_id, actual_branch, limit,
            search_terms=intent.expanded_terms,
            path_overrides=path_overrides,
            trace=trace,
            intent_type=intent.intent_type,
        )
        _phase_log("search_and_fuse")

        entry_points = []
        call_chain = None
        related_files = []
        code_snippets = []

        candidates: Dict[UUID, Tuple[Symbol, float]] = {}
        is_how_it_works = intent.intent_type == "how_it_works"

        # 1. For how_it_works questions, prefer service-layer implementations.
        # HTTP controllers are just API shells; the real algorithm lives here.
        if is_how_it_works:
            for sym, score in self._find_service_entry_points(
                query, intent.expanded_terms, repo_id, actual_branch
            ):
                candidates[sym.id] = (sym, score)

        # 2. Prefer HTTP handlers registered in framework_routes.
        # For how_it_works, controllers are still useful fallbacks but should not
        # outrank service-layer methods.
        route_boost = 0.75 if is_how_it_works else 1.0
        for sym, score in self._find_route_entry_points(
            query, intent.expanded_terms, repo_id, actual_branch
        ):
            existing = candidates.get(sym.id)
            if existing is None or score * route_boost > existing[1]:
                candidates[sym.id] = (sym, score * route_boost)

        # 2.5. 按符号名直接匹配扩展词：覆盖无路由注册/无 service 分层的
        # 项目（如 PyFly 的 reply_zan），让真实实现能进入口点。只对
        # how_it_works 生效，避免普通查询的入口点被符号名匹配污染。
        if is_how_it_works:
            for sym, score in self._find_symbol_name_entry_points(
                intent.expanded_terms, repo_id, actual_branch
            ):
                existing = candidates.get(sym.id)
                if existing is None or score > existing[1]:
                    candidates[sym.id] = (sym, score)

        # 3. Fall back to symbols from the top retrieval hits.
        seen_symbols = set(candidates.keys())
        for hit in hits[:5]:
            if hit.symbol_id and hit.symbol_id not in seen_symbols:
                seen_symbols.add(hit.symbol_id)
                sym = self.db.query(Symbol).filter(Symbol.id == hit.symbol_id).first()
                if sym and not STATIC_PATH_RE.search(sym.file.path if sym.file else ""):
                    candidates[sym.id] = (sym, self._final_score(hit))

        # Keep the top 5 most relevant entry points.
        sorted_candidates = sorted(
            candidates.values(), key=lambda item: -item[1]
        )
        for sym, score in sorted_candidates[:5]:
            entry_point = self._symbol_entry_with_label(sym)
            entry_point.relevance_score = score
            entry_points.append(entry_point)
        _phase_log("entry_points")

        if strategy.include_callers or strategy.include_callees:
            if entry_points:
                root_symbol_id = UUID(entry_points[0].id)
                chain = self._build_call_chain(
                    root_symbol_id,
                    strategy.call_depth,
                    strategy.include_callers,
                    strategy.include_callees,
                    branch=actual_branch,
                )
                call_chain = chain
                chain.flow_summary = self._generate_flow_summary(query, intent.intent_type, entry_points, chain)
                chain_files = self._collect_chain_files(chain)
                related_files.extend(chain_files)
            _phase_log("call_chain")

        flow_summary = call_chain.flow_summary if call_chain else None

        file_chunk_count: Dict[str, int] = {}
        existing_snippet_ids: Set[UUID] = set()

        if is_how_it_works:
            ep_snippets = self._entry_point_snippets(entry_points, branch=actual_branch)
            code_snippets.extend(ep_snippets)
            for s in ep_snippets:
                existing_snippet_ids.add(s.id)
                file_chunk_count[s.file_path] = file_chunk_count.get(s.file_path, 0) + 1

        for hit in hits:
            if len(code_snippets) >= limit:
                break
            if hit.result_id in existing_snippet_ids:
                continue
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
                branch=actual_branch or hit.branch or "main",
                is_override=hit.is_override,
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

        related_files = self._ensure_chinese_enricher(query, repo_id, related_files, actual_branch)
        _phase_log("snippets_build")

        return CodeContext(
            query=query,
            query_intent=intent.intent_type,
            branch=actual_branch or "main",
            matched_concepts=intent.expanded_terms[:10],
            entry_points=entry_points,
            call_chain=call_chain,
            flow_summary=flow_summary,
            related_files=related_files,
            code_snippets=code_snippets,
            total_files=len(related_files),
            total_symbols=len(entry_points),
            search_latency_ms=0,
            meta=SearchMeta(
                requested_branch=requested_branch,
                actual_branch=actual_branch or "main",
                branch_fallback=branch_fallback,
            ),
        )

    def _ensure_chinese_enricher(
        self,
        query: str,
        repo_id: Optional[UUID],
        related_files: List["FileSummary"],
        branch: str = "main",
    ) -> List["FileSummary"]:
        """Boost chinese_enricher.py to related_files for Chinese-aware queries."""
        from schemas import FileSummary

        if not repo_id or not query:
            return related_files

        is_chinese_query = any("\u4e00" <= ch <= "\u9fff" for ch in query)
        has_chinese_concept = "chinese" in query.lower() or "中文" in query
        if not (is_chinese_query or has_chinese_concept):
            return related_files

        existing_paths = {f.path for f in related_files}
        target_path = "backend/services/chinese_enricher.py"
        if target_path in existing_paths:
            return related_files

        code_file = (
            self.db.query(CodeFile)
            .filter(CodeFile.repo_id == repo_id, CodeFile.branch == branch, CodeFile.path == target_path)
            .first()
        )
        if not code_file:
            return related_files

        return [
            FileSummary(
                path=target_path,
                role=self._infer_file_role(target_path),
                relevance_score=0.95,
                key_symbols=[],
            )
        ] + related_files

    def _entry_point_snippets(
        self,
        entry_points: List["SymbolEntry"],
        max_snippets: int = 3,
        branch: str = "main",
    ) -> List["SearchResultItem"]:
        """Build code snippets from the top entry point symbols.

        For ``how_it_works`` queries the raw retrieval hits often miss the core
        implementation body. Promoting entry point symbols guarantees that the
        returned snippets include the methods the user actually asked about.
        """
        from schemas import SearchResultItem

        snippets: List[SearchResultItem] = []
        for ep in entry_points[:max_snippets]:
            try:
                sym = self.db.query(Symbol).filter(Symbol.id == UUID(ep.id)).first()
                if not sym or not sym.file:
                    continue
                embeddings = self.db.query(Embedding).filter(Embedding.file_id == sym.file_id)
                if branch:
                    embeddings = embeddings.filter(Embedding.branch == branch)
                embeddings = embeddings.all()
                hit = _symbol_to_hit(sym, embeddings)
                # Skip placeholder entries that have no embedding coverage.
                if hit.content == f"{sym.type} {sym.name}":
                    continue
                snippets.append(
                    SearchResultItem(
                        id=hit.result_id,
                        file_id=hit.file_id,
                        repo_id=hit.repo_id,
                        repo_name=hit.repo_name,
                        file_path=hit.file_path,
                        language=hit.language,
                        content=hit.content,
                        line=hit.line,
                        score=round(float(ep.relevance_score), 4),
                        score_breakdown={
                            "entry_point_boost": round(float(ep.relevance_score), 4),
                            "symbol": round(hit.symbol_score, 4),
                        },
                        file_role=self._infer_file_role(hit.file_path),
                        branch=branch or sym.branch or "main",
                        is_override=False,
                    )
                )
            except Exception:
                logger.exception("Failed to build entry point snippet for %s", ep.id)
        return snippets

    def _find_service_entry_points(
        self,
        query: str,
        search_terms: Optional[List[str]],
        repo_id: Optional[UUID],
        branch: str = "main",
    ) -> List[Tuple[Symbol, float]]:
        """For how_it_works queries, find service-layer functions whose names or
        Chinese flow labels match the expanded query terms.

        Service-layer symbols (layer='service' in symbol_flow_labels) are the
        real algorithm implementations; surfacing them as entry points produces
        better flow summaries than HTTP controller shells.
        """
        if not repo_id or not search_terms:
            return []

        patterns = [t.lower() for t in search_terms if len(t) > 1]
        if not patterns:
            return []

        service_symbols = (
            self.db.query(Symbol)
            .join(SymbolFlowLabel)
            .join(CodeFile)
            .filter(
                Symbol.repo_id == repo_id,
                Symbol.branch == branch,
                Symbol.type.in_(["function", "method"]),
                SymbolFlowLabel.layer == "service",
                or_(
                    CodeFile.path.ilike("backend/services/%"),
                    CodeFile.path.ilike("packages/core/src/service/%"),
                ),
            )
            .all()
        )

        # Core orchestrators should surface as entry points for how_it_works queries.
        core_orchestrators = {
            "hybrid_search", "search_with_context", "analyze",
            "_execute_strategy", "_search_and_fuse",
        }

        matched: Dict[UUID, Tuple[Symbol, float]] = {}
        for sym in service_symbols:
            name_lower = (sym.name or "").lower()
            is_core = name_lower in core_orchestrators
            is_private = sym.name.startswith("_")

            for pattern in patterns:
                if pattern in name_lower:
                    score = 0.88
                    if pattern in ("search", "query", "retrieval", "intent", "analyze"):
                        score = 0.93
                    if is_core:
                        score = 0.96
                    if is_private and not is_core:
                        score *= 0.85
                    if sym.id not in matched or score > matched[sym.id][1]:
                        matched[sym.id] = (sym, score)
                    break

            label = sym.flow_label
            if label:
                chinese_name_lower = (label.chinese_name or "").lower()
                for pattern in patterns:
                    if pattern in chinese_name_lower:
                        score = 0.90
                        if is_core:
                            score = 0.96
                        if is_private and not is_core:
                            score *= 0.85
                        if sym.id not in matched or score > matched[sym.id][1]:
                            matched[sym.id] = (sym, score)
                        break

        return list(matched.values())

    def _find_symbol_name_entry_points(
        self,
        search_terms: Optional[List[str]],
        repo_id: Optional[UUID],
        branch: str = "main",
    ) -> List[Tuple[Symbol, float]]:
        """按符号名直接匹配扩展词，补充路由/service 层覆盖不到的实现入口。

        部分项目（如 PyFly）的 AJAX 接口（reply_zan 等）没有注册到
        framework_routes，且项目无 backend/services 分层，导致入口点只能
        靠 RRF 融合后的 hits 兜底——而真实实现往往被通用扩展词（post/
        thread）的大量命中挤到重排输入之外。此方法对所有函数/方法符号做
        符号名匹配，让查询的核心概念（点赞→zan/like）能命中对应实现。
        """
        if not repo_id or not search_terms:
            return []

        # 忽略过短的模式（单字符会匹配大量压缩 JS 符号），保留查询核心词
        patterns = [t.lower() for t in search_terms if len(t) >= 3]
        if not patterns:
            return []

        symbols = (
            self.db.query(Symbol)
            .join(CodeFile)
            .filter(
                Symbol.repo_id == repo_id,
                Symbol.branch == branch,
                Symbol.type.in_(["function", "method"]),
                CodeFile.path.notlike("%static/%"),
            )
            .all()
        )

        matched: Dict[UUID, Tuple[Symbol, float]] = {}
        # 每个 pattern 最多贡献 1 个得分最高的符号：通用扩展词（如帖子→
        # post）会匹配同项目大量 post_* 函数，若不加限制会占满入口点名额，
        # 把真实核心实现（点赞→reply_zan）挤出 top5。
        for pattern in patterns:
            best: Optional[Tuple[Symbol, float]] = None
            for sym in symbols:
                name_lower = (sym.name or "").lower()
                if pattern not in name_lower:
                    continue
                # 短 pinyin 缩写（zan 等 2~3 字符）通常是查询核心概念的真实
                # 实现名，给与更高权重，避免被 post 这类泛扩展词压过。
                if len(pattern) <= 3:
                    score = 0.98
                else:
                    score = 0.88 + 0.06 * min(len(pattern) / 6.0, 1.0)
                if sym.name.startswith(pattern):
                    score += 0.03
                if best is None or score > best[1]:
                    best = (sym, score)
            if best is not None:
                sid, sc = best
                if sid not in matched or sc > matched[sid][1]:
                    matched[sid] = (sid, sc)

        return list(matched.values())

    def _symbol_entry_with_label(
        self, sym: Symbol, label: Optional[SymbolFlowLabel] = None
    ) -> "SymbolEntry":
        from schemas import SymbolEntry

        if label is None:
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
        branch: str = "main",
    ) -> "CallChain":
        from schemas import CallChain, SymbolEntry

        root = self.db.query(Symbol).filter(Symbol.id == root_symbol_id).first()
        if not root:
            return CallChain(
                root=SymbolEntry(id=str(root_symbol_id), name="", type="", file_path="", line=0),
                upstream=[], downstream=[], depth=0,
            )

        root_entry = self._symbol_entry_with_label(root)

        caller_ids: List[UUID] = []
        callee_ids: List[UUID] = []
        if include_callers:
            caller_ids = self._query_callers(root_symbol_id, depth, branch)
        if include_callees:
            callee_ids = self._query_callees(root_symbol_id, depth, branch)

        related_ids = set(caller_ids) | set(callee_ids)
        entries = self._symbol_entries_by_ids(related_ids)

        # 排除静态/第三方目录的符号（layui/minified JS 会产出大量单字符符号
        # 如 `s`），避免调用链显示成「一堆单独的英文字母」。
        def _non_static(sym_id: UUID) -> bool:
            entry = entries.get(sym_id)
            return bool(entry) and not STATIC_PATH_RE.search(entry.file_path)

        upstream = [entries[cid] for cid in caller_ids if cid in entries and _non_static(cid)]
        downstream = [entries[cid] for cid in callee_ids if cid in entries and _non_static(cid)]

        return CallChain(
            root=root_entry,
            upstream=upstream,
            downstream=downstream,
            depth=depth,
        )

    def _symbol_entries_by_ids(
        self, symbol_ids: Set[UUID]
    ) -> Dict[UUID, "SymbolEntry"]:
        """Batch load symbols and their flow labels in two queries.

        Avoids the N+1 pattern when building call chains.
        """
        from schemas import SymbolEntry

        if not symbol_ids:
            return {}

        symbols = self.db.query(Symbol).filter(Symbol.id.in_(list(symbol_ids))).all()
        labels = {
            label.symbol_id: label
            for label in self.db.query(SymbolFlowLabel)
            .filter(SymbolFlowLabel.symbol_id.in_(list(symbol_ids)))
            .all()
        }

        result: Dict[UUID, SymbolEntry] = {}
        for sym in symbols:
            result[sym.id] = self._symbol_entry_with_label(sym, labels.get(sym.id))
        return result

    def _query_callers(self, symbol_id: UUID, depth: int, branch: str = "main") -> List[UUID]:
        results = []
        current = {symbol_id}
        visited = {symbol_id}

        for _ in range(depth):
            next_level = set()
            for sid in current:
                edges = self.db.query(CallGraphEdge).filter(
                    CallGraphEdge.target_symbol_id == sid,
                    CallGraphEdge.branch == branch,
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

    def _query_callees(self, symbol_id: UUID, depth: int, branch: str = "main") -> List[UUID]:
        results = []
        current = {symbol_id}
        visited = {symbol_id}

        for _ in range(depth):
            next_level = set()
            for sid in current:
                edges = self.db.query(CallGraphEdge).filter(
                    CallGraphEdge.source_symbol_id == sid,
                    CallGraphEdge.branch == branch,
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

        hits = self._symbols_to_hits(symbols)
        for hit in hits:
            hit.graph_score = 0.7
            hit.sources.add("graph")

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

        # 2b. Static assets / third-party bundles. Generic rule based on
        # common frontend build conventions: any web file under a static
        # resource directory is a built bundle or vendor lib, not source
        # logic, so it carries almost no retrieval value for code search.
        if name.endswith((".js", ".css", ".html", ".map", ".scss", ".less")):
            if any(seg in parts for seg in ("static", "assets", "dist", "public", "build")):
                return "static"

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
            "vo": "model",
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
                # retrieval logic are more precisely "analyzer". "searcher" is
                # intentionally excluded because it orchestrates the whole search
                # pipeline and should be treated as a service entry point.
                if role == "service" and any(
                    token in name_no_ext
                    for token in ("analyzer", "parser", "enricher", "indexer")
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

    def _find_route_entry_points(
        self,
        query: str,
        search_terms: Optional[List[str]],
        repo_id: Optional[UUID],
        branch: str = "main",
    ) -> List[Tuple[Symbol, float]]:
        """Prioritize HTTP handler symbols that match the query in framework_routes.

        When a user asks about a feature, the real entry point is usually the
        HTTP handler (controller / API endpoint) rather than an internal helper
        or core adapter. Route matches are scored slightly below a perfect M3
        hit but above most generic symbols so they surface as entry points.
        """
        if not repo_id or not search_terms:
            return []

        patterns = [t.lower() for t in search_terms if len(t) > 1]
        if not patterns:
            return []

        routes = (
            self.db.query(FrameworkRoute)
            .filter(FrameworkRoute.repo_id == repo_id, FrameworkRoute.branch == branch)
            .all()
        )

        matched: Dict[UUID, Tuple[Symbol, float]] = {}
        for route in routes:
            path_lower = (route.path or "").lower()
            handler_lower = (route.handler_symbol or "").lower()
            for pattern in patterns:
                if pattern in path_lower or pattern in handler_lower:
                    sym = (
                        self.db.query(Symbol)
                        .filter(
                            Symbol.repo_id == repo_id,
                            Symbol.branch == branch,
                            Symbol.name == route.handler_symbol,
                            Symbol.file_id == route.file_id,
                        )
                        .first()
                    )
                    if sym is None:
                        break
                    # 静态/第三方目录的 handler（压缩 JS 产物等）不作为入口点
                    if STATIC_PATH_RE.search(sym.file.path if sym.file else ""):
                        break
                    # Boost controllers/handlers so they outrank internal helpers.
                    score = 0.92
                    if pattern in handler_lower:
                        score = 0.96
                    if sym.id not in matched or score > matched[sym.id][1]:
                        matched[sym.id] = (sym, score)
                    break

        return list(matched.values())

    def _search_and_fuse(
        self,
        query: str,
        repo_id: Optional[UUID],
        branch: str,
        limit: int,
        search_terms: Optional[List[str]] = None,
        path_overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[SearchTrace] = None,
        intent_type: Optional[str] = None,
    ) -> List[_Hit]:
        """Unified retrieval pipeline with branch merge support.

        For business branches: main results (excluding files deleted by the
        branch) ∪ branch diff results. Override results are marked via hit
        attribute ``is_override``.
        """
        if not repo_id:
            return self._single_branch_search_and_fuse(
                query, repo_id, branch, limit, search_terms, path_overrides, trace, intent_type
            )

        repo = self.db.query(Repository).filter(Repository.id == repo_id).first()
        default_branch = repo.default_branch or "main" if repo else "main"

        if branch == default_branch:
            return self._single_branch_search_and_fuse(
                query, repo_id, branch, limit, search_terms, path_overrides, trace, intent_type
            )

        # Business branch: merge main + diff
        deleted_paths = set()
        if repo and repo.branch_deleted_files:
            deleted_paths = set(json.loads(repo.branch_deleted_files or "{}").get(branch, []))

        main_hits = self._single_branch_search_and_fuse(
            query, repo_id, default_branch, limit * 2, search_terms, path_overrides, trace, intent_type
        )
        branch_hits = self._single_branch_search_and_fuse(
            query, repo_id, branch, limit * 2, search_terms, path_overrides, trace, intent_type
        )

        # Mark overrides and filter main results deleted by branch
        for hit in main_hits:
            hit.is_override = False
        for hit in branch_hits:
            hit.is_override = True

        main_hits = [h for h in main_hits if h.file_path not in deleted_paths]

        # Merge by (file_path, line), branch hits override main hits
        by_key: Dict[Tuple[str, int], _Hit] = {}
        for hit in main_hits:
            by_key[(hit.file_path, hit.line)] = hit
        for hit in branch_hits:
            by_key[(hit.file_path, hit.line)] = hit

        merged = sorted(by_key.values(), key=lambda h: h.score, reverse=True)
        return merged[:limit * 2]

    def _single_branch_search_and_fuse(
        self,
        query: str,
        repo_id: Optional[UUID],
        branch: str,
        limit: int,
        search_terms: Optional[List[str]] = None,
        path_overrides: Optional[Dict[str, Any]] = None,
        trace: Optional[SearchTrace] = None,
        intent_type: Optional[str] = None,
    ) -> List[_Hit]:
        """Unified retrieval pipeline for a single branch: vector + sparse + symbol + bm25 + graph,
        then RRF fusion and two-stage reranking.
        """
        self.db.execute(text("SET hnsw.ef_search = 128"))

        overrides = path_overrides or {}
        enabled_paths: Set[str] = set(overrides.get("enabled", {
            "vector", "sparse", "symbol", "bm25", "graph",
        }))
        top_k_overrides: Dict[str, int] = overrides.get("top_k", {})

        def _top_k(name: str, default: int = 20) -> int:
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
            "vector", lambda top_k: self._vector_search(query_embedding, repo_id, branch, top_k=top_k)
        )

        symbol_results = _run_path(
            "symbol", lambda top_k: self._symbol_search_multi(query, search_terms, repo_id, branch, top_k=top_k)
        )

        is_chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
        bm25_concepts = self.intent_analyzer._extract_concepts(query, is_chinese)
        for term in search_terms or []:
            if term != query and term not in bm25_concepts:
                bm25_concepts.append(term)
        bm25_results = _run_path(
            "bm25", lambda top_k: self._bm25_search(query, repo_id, branch, top_k=top_k, concepts=bm25_concepts)
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
            return self._sparse_search(query_sparse, repo_id, branch, top_k=top_k)

        sparse_results = _run_path("sparse", _sparse_runner)

        graph_results: List[_Hit] = []
        if "graph" in enabled_paths and symbol_results:
            try:
                graph_results = _run_path(
                    "graph", lambda top_k: self._graph_search(symbol_results, repo_id, branch, top_k=top_k)
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
        # 过滤跨项目误命中：独有功能查询在无关仓库通常只有单路弱证据
        # （vector 0.53~0.57 泛匹配），此处按 _is_confident_hit 过滤后再
        # 进入重排，避免把无关结果一路送到前端。静态/构建产物目录
        # （压缩 JS 等）在任何查询下都不进入结果。
        hits = [
            h for h in hits
            if not STATIC_PATH_RE.search(h.file_path) and _is_confident_hit(h)
        ]
        if trace is not None:
            trace.set_fusion(RRF_K, hits)

        schema_results = [self._to_schema(hit, branch=branch) for hit in hits[:limit * 2]]
        reranked = CodeReranker().rerank(
            query, schema_results, search_terms=search_terms, intent_type=intent_type
        )

        m3_reranker = get_m3_reranker()
        # bge-reranker-base 主要训练于英文文本：中文问句 + 英文代码的
        # 交叉编码分数会整体坍缩失真（中英 token 在嵌入空间未对齐），
        # 导致 getter/setter、VO 等短片段反超真正的实现代码。
        # 纯英文替换又会丢失中文语义约束（扩展词不精准时误导打分），
        # 因此混合：保留原始中文 + 拼接语义扩展出的英文代码词，
        # 让 M3 在中英双语义空间打分。扩展不出英文词时回落到原始 query。
        m3_query = query
        if search_terms and re.search(r"[\u4e00-\u9fff]", query):
            english_terms = [t for t in search_terms if re.match(r"^[a-zA-Z0-9_]+$", t)]
            if english_terms:
                m3_query = query + " " + " ".join(english_terms[:6])
        # bge-reranker-base 在 CPU 上对每个候选对做交叉编码，耗时与输入规模成正比
        # （本地约 70ms/对）。输入数量须与最终输出条数对齐：benchmark/评测按
        # 「期望文件出现在 top20」判定，若 M3 输入过少（如 12）会把部分真实
        # 命中（fusion 排名 5~12 之后）挤出重排输入，导致召回退化。20 对约
        # 1.4s，配合 BM25 两阶段优化后整体查询仍在 5s 硬指标内。
        final_schemas = m3_reranker.rerank(m3_query, reranked[: min(limit * 2, 20)], top_k=limit)

        # M3 reranker recomputes scores from scratch and discards the role
        # weights applied by CodeReranker. Re-apply them when the model is
        # loaded so the final ranking respects file roles and intent tuning.
        if m3_reranker.model is not None:
            intent_boost = CodeReranker._INTENT_ROLE_BOOST.get(intent_type, {})
            code_reranker = CodeReranker()
            for schema in final_schemas:
                role = getattr(schema, "file_role", None) or "other"
                weight = ROLE_WEIGHTS.get(role, 1.0)
                weight *= intent_boost.get(role, 1.0)
                if code_reranker._is_shallow_snippet(schema.content):
                    weight *= 0.7
                if code_reranker._is_minified_snippet(schema.content):
                    weight *= 0.3
                schema.score *= weight
            final_schemas.sort(key=lambda x: -x.score)

        if trace is not None:
            trace.set_rerank(
                code_reranker_input_count=len(schema_results),
                code_reranker_output=reranked,
                m3_reranker_input_count=len(reranked),
                m3_reranker_output=final_schemas,
            )

        # Map reranked schemas back to _Hit objects so callers can still
        # access hit.symbol_id and other internal metadata. Preserve the RRF
        # score for debugging and overwrite hit.score with the M3 reranked
        # score so that downstream callers see the final ranking score.
        hit_by_id = {hit.result_id: hit for hit in hits}
        final_hits: List[_Hit] = []
        for schema in final_schemas:
            hit = hit_by_id.get(schema.id)
            if hit:
                hit.score = schema.score
                final_hits.append(hit)
        return final_hits

    def debug_search(
        self,
        query: str,
        repo_id: UUID,
        branch: str = "main",
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
            branch=branch,
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
        branch: str = "main",
        limit: int = 20,
    ) -> List[SearchResultItem]:
        logger.info("Hybrid search query=%s repo_id=%s branch=%s", query, repo_id, branch)
        # Analyze without LLM expansion (network call) so the hot path stays
        # fast; SEMANTIC_MAP / domain-synonym expansions still apply.
        intent = self.intent_analyzer.analyze(
            query,
            repo_id=str(repo_id) if repo_id else None,
            db=self.db,
            enable_llm_expand=False,
        )
        actual_branch, _ = self._resolve_branch(repo_id, branch)
        hits = self._search_and_fuse(
            query, repo_id, actual_branch, limit,
            search_terms=intent.expanded_terms,
            intent_type=intent.intent_type,
        )
        return [self._to_schema(hit, branch=actual_branch) for hit in hits[:limit]]

    def symbol_search(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        branch: str = "main",
        limit: int = 20,
    ) -> List[SearchResultItem]:
        actual_branch, _ = self._resolve_branch(repo_id, branch)
        symbols = self._symbol_search_raw(query, repo_id, actual_branch, limit * 3)
        hits = self._symbols_to_hits(symbols)
        hits.sort(key=lambda h: h.symbol_score, reverse=True)
        return [self._to_schema(hit, branch=actual_branch) for hit in hits[:limit]]

    def _vector_search(
        self,
        query_embedding: List[float],
        repo_id: Optional[UUID],
        branch: str = "main",
        top_k: int = 50,
        limit: int = 50,
    ) -> List[_Hit]:
        rows = self.embedding_repo.vector_search(query_embedding, repo_id, branch, top_k)

        hits: List[_Hit] = []
        for row in rows:
            # 静态/构建产物目录的 chunk 不参与向量检索（压缩 JS 等对语义检索无意义）
            if STATIC_PATH_RE.search(row["file_path"]):
                continue
            distance = row.get("distance")
            if isinstance(distance, str):
                distance = float(distance)
            score = max(0.0, 1.0 - distance)
            # 无相似度下限时，任意查询都会拿到 top-k 个「相对最高分」的 chunk
            # （无关查询也能有 0.4 左右的分数）。低于阈值的命中与查询无关，
            # 直接丢弃，避免 RRF 融合后把无关结果当命中返回。
            if score < VECTOR_SIMILARITY_THRESHOLD:
                continue
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
                    branch=row["branch"],
                )
            )
        return hits

    def _symbol_search_raw(
        self,
        query: str,
        repo_id: Optional[UUID],
        branch: str = "main",
        limit: int = 50,
    ) -> List[Symbol]:
        return self.symbol_repo.search_by_name(query, repo_id, branch, limit)

    def _symbol_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        branch: str = "main",
        top_k: int = 50,
    ) -> List[_Hit]:
        symbols = self._symbol_search_raw(query, repo_id, branch, top_k)
        # 过滤通用框架/工具函数（HTTP 方法封装、通用 CRUD 命名）与
        # 静态/第三方目录符号，避免与查询扩展出的泛化词撞车造成误命中
        symbols = [
            s for s in symbols
            if SymbolNormalizer.normalize(s.name) not in GENERIC_SYMBOL_NAMES
            and not STATIC_PATH_RE.search(s.file.path if s.file else "")
        ]
        symbol_by_id = {sym.id: sym for sym in symbols}
        hits = self._symbols_to_hits(symbols)
        for hit in hits:
            sym = symbol_by_id[hit.symbol_id]
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
        return hits

    def _symbol_search_multi(
        self,
        query: str,
        search_terms: Optional[List[str]],
        repo_id: Optional[UUID],
        branch: str = "main",
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
            for hit in self._symbol_search(term, repo_id, branch, top_k):
                key = hit.symbol_id or hit.result_id
                existing = best.get(key)
                if existing is None or hit.symbol_score > existing.symbol_score:
                    best[key] = hit
        return sorted(best.values(), key=lambda h: h.symbol_score, reverse=True)[:top_k]

    @staticmethod
    def _to_or_tsquery(terms: List[str]) -> str:
        """Build a PostgreSQL OR tsquery from a list of search terms.

        Strips punctuation/whitespace and joins remaining tokens with ``|``.
        Returns an empty string when no valid terms remain.
        """
        cleaned = []
        for term in terms:
            for token in re.split(r"[^\w\u4e00-\u9fff]+", term):
                token = token.strip()
                if token and len(token) >= 2:
                    cleaned.append(token)
        return " | ".join(cleaned)

    def _bm25_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        branch: str = "main",
        top_k: int = 50,
        concepts: Optional[List[str]] = None,
    ) -> List[_Hit]:
        params: Dict[str, Any] = {
            "query": query,
            "repo_id": str(repo_id) if repo_id else None,
            "branch": branch,
            "limit": top_k,
        }

        # Build OR tsquery so that matching any term contributes to rank.
        query_terms = [query] + (concepts or [])
        query_or = self._to_or_tsquery(query_terms)
        params["query_or"] = query_or if query_or else query
        logger.info("BM25 debug concepts(%d): %s", len(concepts or []), (concepts or [])[:20])

        # 静态/构建产物/第三方目录的大文件不参与 BM25：关键词检索价值低，
        # 且 minified 产物单 chunk 可达数万字符，实时 to_tsvector 分词成本极高
        # （PyFly 的 layui 压缩 JS 曾导致 BM25 路径耗时 17s+）。
        # 与 _infer_file_role 的 static 判定保持一致（目录段含 static/assets/dist 等）。
        params["static_path_regex"] = r"(^|/)(static|assets|dist|public|build|vendor|libs|node_modules)(/|$)"

        # Direct phrase match bonus.
        params["query_like"] = f"%{query}%"

        # Concept-level fuzzy fallback for Chinese and short terms.
        # 只对纯中文概念做 ILIKE：英文概念（auth/login/token）已被 english
        # content 的 GIN 分支覆盖，再做 ILIKE 会让候选集随概念数线性膨胀
        # （11 个概念 × 2 个短字段命中面广，rank 阶段对大量候选构建 tsvector
        # 实测 700ms+）。中文概念在英文代码 content 中不命中，必须靠中文
        # 摘要/关键词的模糊匹配补充召回。
        concept_where_ee: List[str] = []
        for idx, concept in enumerate(concepts or []):
            if len(concept) < 2:
                continue
            if not re.fullmatch(r"[\u4e00-\u9fff]+", concept):
                continue
            like_key = f"concept_{idx}_like"
            params[like_key] = f"%{concept}%"
            concept_where_ee.append(f"ee.chinese_summary ILIKE :{like_key}")
            concept_where_ee.append(f"ee.keywords ILIKE :{like_key}")

        # 两阶段 BM25：
        #  1) cand：UNION 候选筛选，每条分支独立优化，让 Postgres 把
        #     to_tsvector('english', e.content) @@ 下推到 GIN 表达式索引
        #     （idx_embeddings_content_fts）。实测「OR 合并谓词」会让优化器
        #     在 Join 之上对全部行做 tsvector 构建（auth/login 类命中面广时
        #     1.5~2.2s）；拆分后 english 分支走 Bitmap Index Scan ~1ms。
        #     simple(content) 分支与 english 分支召回几乎重合且无索引（全扫
        #     25KB 文本分词 ~650ms），故移除，仅保留 ee 短字段分支补充中文
        #     摘要/关键词命中。
        #  2) rank：只对候选集（数十行）构建 tsvector 计算 ts_rank_cd，
        #     避免对全表行重复构建。
        sql = text(
            f"""
            WITH cand AS MATERIALIZED (
                SELECT e.id AS eid
                FROM embeddings e
                WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
                  AND (:branch IS NULL OR e.branch = :branch)
                  AND to_tsvector('english', e.content) @@ to_tsquery('english', :query_or)
                UNION
                SELECT e.id AS eid
                FROM embeddings e
                JOIN embedding_enrichments ee ON ee.embedding_id = e.id
                WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
                  AND (:branch IS NULL OR e.branch = :branch)
                  AND (
                        to_tsvector('simple', ee.chinese_summary) @@ to_tsquery('simple', :query_or)
                        OR to_tsvector('simple', ee.keywords) @@ to_tsquery('simple', :query_or)
                        OR ee.chinese_summary ILIKE :query_like
                        OR ee.keywords ILIKE :query_like
                        {(" OR " + " OR ".join(concept_where_ee)) if concept_where_ee else ""}
                      )
            )
            SELECT x.embedding_id,
                   x.file_id,
                   x.repo_id,
                   x.branch,
                   x.repo_name,
                   x.content,
                   x.start_line,
                   x.end_line,
                   x.file_path,
                   x.language,
                   GREATEST(
                       ts_rank_cd(x.tsv_simple, to_tsquery('simple', :query_or)),
                       COALESCE(ts_rank_cd(x.tsv_summary, to_tsquery('simple', :query_or)), 0),
                       COALESCE(ts_rank_cd(x.tsv_keywords, to_tsquery('simple', :query_or)), 0),
                       CASE WHEN x.content ILIKE :query_like THEN 0.2 ELSE 0 END,
                       CASE WHEN x.chinese_summary ILIKE :query_like THEN 0.6 ELSE 0 END,
                       CASE WHEN x.keywords ILIKE :query_like THEN 0.9 ELSE 0 END
                   ) AS rank
            FROM (
                SELECT e.id AS embedding_id,
                       e.file_id,
                       e.repo_id,
                       e.branch,
                       r.name AS repo_name,
                       e.content,
                       e.start_line,
                       e.end_line,
                       f.path AS file_path,
                       f.language,
                       ee.chinese_summary,
                       ee.keywords,
                       -- 只对候选集构建一次 tsvector，避免 GREATEST/WHERE 中重复实时分词。
                       -- 不再构建 english 版 content tsvector：english 词干化在
                       -- 大 chunk 上最贵（候选数十行时 ~700ms），召回已由 cand 中
                       -- english GIN 索引分支保证，排序用 simple/summary/keywords。
                       to_tsvector('simple', e.content) AS tsv_simple,
                       to_tsvector('simple', ee.chinese_summary) AS tsv_summary,
                       to_tsvector('simple', ee.keywords) AS tsv_keywords
                FROM embeddings e
                JOIN cand ON cand.eid = e.id
                JOIN code_files f ON f.id = e.file_id
                JOIN repositories r ON r.id = e.repo_id
                LEFT JOIN embedding_enrichments ee ON ee.embedding_id = e.id
                WHERE f.path !~* :static_path_regex
            ) x
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        import time as _time
        _t0 = _time.perf_counter()
        rows = self.db.execute(
            sql,
            params,
        ).fetchall()
        logger.info(
            "BM25 db.execute took %.0fms, rows=%d, concepts=%d",
            (_time.perf_counter() - _t0) * 1000,
            len(rows),
            len(concepts or []),
        )

        hits: List[_Hit] = []
        for row in rows:
            rank = row.rank
            if isinstance(rank, str):
                rank = float(rank)
            # ts_rank_cd can produce large values for short queries/texts.
            # Cap and normalize so BM25 scores stay in the same ballpark as
            # vector/symbol scores and do not dominate the combined score.
            normalized_rank = min(rank, 1.5)
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
                    bm25_score=normalized_rank,
                    sources={"bm25"},
                    branch=row.branch,
                )
            )
        return hits

    def _graph_search(
        self,
        symbol_hits: List[_Hit],
        repo_id: Optional[UUID],
        branch: str = "main",
        top_k: int = 50,
    ) -> List[_Hit]:
        if not symbol_hits:
            return []

        symbol_ids = [h.symbol_id for h in symbol_hits if h.symbol_id and h.sources == {"symbol"}]
        if symbol_ids:
            related_symbols = self.symbol_repo.get_related_by_edges(symbol_ids, branch, top_k)
        else:
            file_ids = list({h.file_id for h in symbol_hits})
            related_symbols = self.symbol_repo.get_by_file_ids(file_ids, branch, top_k)

        hits = self._symbols_to_hits(related_symbols)
        for hit in hits:
            hit.graph_score = 0.7
            hit.sources.add("graph")
        return hits

    def _file_embeddings(self, file_id: UUID) -> List[Embedding]:
        return self.embedding_repo.get_by_file_id(file_id)

    def _symbols_to_hits(self, symbols: List[Symbol]) -> List[_Hit]:
        """Convert multiple symbols to hits with a single batched embeddings query.

        Avoids the N+1 pattern caused by calling ``_file_embeddings`` per symbol.
        """
        if not symbols:
            return []
        file_ids = list({s.file_id for s in symbols})
        embeddings_by_file = self.embedding_repo.get_by_file_ids(file_ids)
        hits = []
        for sym in symbols:
            hit = _symbol_to_hit(sym, embeddings_by_file.get(sym.file_id, []))
            hits.append(hit)
        return hits

    def _sparse_search(
        self,
        query_sparse: Dict[int, float],
        repo_id: Optional[UUID],
        branch: str = "main",
        top_k: int = 50,
    ) -> List[_Hit]:
        if not query_sparse:
            return []

        query_tokens = list(query_sparse.keys())

        rows = self.db.query(
            SparseEmbedding.embedding_id,
            SparseEmbedding.token_id,
            SparseEmbedding.weight,
        ).join(
            Embedding,
            Embedding.id == SparseEmbedding.embedding_id,
        ).filter(
            SparseEmbedding.token_id.in_(query_tokens),
        )

        if branch:
            rows = rows.filter(Embedding.branch == branch)
        if repo_id:
            rows = rows.filter(Embedding.repo_id == repo_id)

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

        # 过滤噪声级命中（无关查询的 token 权重乘积趋近于 0），避免
        # 单条 0.005 的稀疏命中进入 RRF 融合并出现在最终结果里。
        sorted_eids = sorted(
            (eid for eid, s in scores.items() if s >= SPARSE_SCORE_THRESHOLD),
            key=lambda eid: -scores[eid],
        )[:top_k]

        embeddings = self.db.query(Embedding).filter(
            Embedding.id.in_(sorted_eids)
        ).all()

        hits = []
        for emb in embeddings:
            # 静态/第三方目录的 chunk 不参与稀疏检索（与向量/BM25 一致）
            if STATIC_PATH_RE.search(emb.file.path if emb.file else ""):
                continue
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
                branch=emb.branch,
            ))
        return hits

    def _final_score(self, hit: _Hit) -> float:
        # If the M3 reranker has overwritten hit.score, use it as the final
        # score. Otherwise fall back to the RRF combined score.
        if hit.score:
            return hit.score
        return _combined_score(hit)

    def _to_schema(self, hit: _Hit, branch: str = "main") -> SearchResultItem:
        # ``hit.score`` may have been overwritten by the M3 reranker; if so we
        # use it as the final score. Otherwise fall back to the RRF score.
        final_score = self._final_score(hit)
        rrf_score = getattr(hit, 'rrf_score', _combined_score(hit))
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
                "rrf": round(rrf_score, 4),
                "final": round(final_score, 4),
            },
            file_role=self._infer_file_role(hit.file_path),
            branch=branch or hit.branch or "main",
            is_override=hit.is_override,
        )


from repositories import EmbeddingRepository, SymbolRepository