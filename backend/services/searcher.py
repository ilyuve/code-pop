"""Hybrid search engine with intent-aware retrieval and degradation fallback."""

import collections
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from models import CallGraphEdge, CodeFile, Embedding, SparseEmbedding, Symbol
from schemas import SearchResultItem
from services.embedder import Embedder
from services.degradation_tracker import get_degradation_tracker
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


def _min_max_normalize(scores: List[float]) -> List[float]:
    if not scores:
        return scores
    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        return [1.0 for _ in scores]
    return [(s - min_score) / (max_score - min_score) for s in scores]


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


def _rrf_fuse(results_by_source: Dict[str, List[_Hit]]) -> List[_Hit]:
    rrf_scores = collections.defaultdict(float)
    hit_by_key = {}

    for source_name, hits in results_by_source.items():
        for rank, hit in enumerate(hits, start=1):
            key = (hit.file_id, hit.line)
            rrf_scores[key] += 1.0 / (RRF_K + rank)
            if key not in hit_by_key or hit.vector_score > hit_by_key[key].vector_score:
                hit_by_key[key] = hit

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
    """Intent-aware hybrid code search with degradation fallback."""

    def __init__(self, db: Session):
        self.db = db
        self.embedder = Embedder()
        self.embedding_repo = EmbeddingRepository(db)
        self.symbol_repo = SymbolRepository(db)
        self.intent_analyzer = get_intent_analyzer()
        self._degraded_components: Set[str] = set()
        self._degradation_reasons: List[str] = []

    def _record_degradation(self, component: str, reason: str, fallback: str):
        self._degraded_components.add(component)
        self._degradation_reasons.append(reason)
        get_degradation_tracker().record(
            component=component,
            error_type="SearchDegradation",
            error_message=reason,
            fallback_action=fallback,
        )

    def search_with_context(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
        intent=None,
    ) -> "CodeContext":
        from schemas import CallChain, CodeContext, FileSummary, SymbolEntry

        self._degraded_components = set()
        self._degradation_reasons = []

        if intent is None:
            intent = self.intent_analyzer.analyze(query)
        logger.info("Query intent: %s, strategy: %s", intent.intent_type, intent.search_strategy)

        strategy = intent.search_strategy
        hits = self._execute_strategy(intent, repo_id, limit)

        entry_points = []
        call_chain = None
        related_files = []
        code_snippets = []

        seen_symbols = set()
        for hit in hits[:5]:
            if hit.symbol_id and hit.symbol_id not in seen_symbols:
                seen_symbols.add(hit.symbol_id)
                entry_points.append(SymbolEntry(
                    id=str(hit.symbol_id),
                    name=hit.symbol_name or "",
                    type="function",
                    file_path=hit.file_path,
                    line=hit.line,
                    relevance_score=hit.vector_score + hit.symbol_score,
                ))

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
                chain_files = self._collect_chain_files(chain)
                related_files.extend(chain_files)

        seen_files = set()
        for hit in hits[:limit]:
            if hit.file_path not in seen_files:
                seen_files.add(hit.file_path)
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
                        "final": round(self._final_score(hit), 4),
                    },
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
            related_files=related_files,
            code_snippets=code_snippets,
            total_files=len(related_files),
            total_symbols=len(entry_points),
            search_latency_ms=0,
            degraded=len(self._degraded_components) > 0,
            degradation_reason="; ".join(self._degradation_reasons) if self._degradation_reasons else None,
            unavailable_sources=list(self._degraded_components),
        )

    def _execute_strategy(
        self,
        intent,
        repo_id: Optional[UUID],
        limit: int,
    ) -> List[_Hit]:
        strategy = intent.search_strategy
        all_hits: List[_Hit] = []

        search_terms = intent.expanded_terms if strategy.expand_synonyms else [intent.original]

        for term in search_terms[:5]:
            hits: List[_Hit] = []

            if strategy.primary == "vector":
                try:
                    query_embedding = self.embedder.encode_query(term)
                    hits = self._vector_search(query_embedding, repo_id, limit=30)
                except Exception as e:
                    logger.warning("Vector search degraded for term '%s': %s", term, e)
                    self._record_degradation("vector_search", str(e), "Skipping vector search")

            elif strategy.primary == "symbol":
                try:
                    hits = self._symbol_search(term, repo_id, top_k=30)
                except Exception as e:
                    logger.warning("Symbol search degraded for term '%s': %s", term, e)
                    self._record_degradation("symbol_search", str(e), "Skipping symbol search")

            elif strategy.primary == "call_graph":
                try:
                    sym_hits = self._symbol_search(term, repo_id, top_k=10)
                    hits = sym_hits
                    if strategy.include_callers or strategy.include_callees:
                        for h in sym_hits[:3]:
                            if h.symbol_id:
                                try:
                                    graph_hits = self._graph_search_from_symbol(
                                        h.symbol_id, repo_id, strategy.call_depth
                                    )
                                    hits.extend(graph_hits)
                                except Exception as e:
                                    logger.warning("Graph search degraded for term '%s': %s", term, e)
                                    self._record_degradation("graph_search", str(e), "Skipping graph search")
                except Exception as e:
                    logger.warning("Symbol search degraded for call_graph term '%s': %s", term, e)
                    self._record_degradation("symbol_search", str(e), "Skipping call_graph search")

            elif strategy.primary == "bm25":
                try:
                    hits = self._bm25_search(term, repo_id, limit=30)
                except Exception as e:
                    logger.warning("BM25 search degraded for term '%s', falling back to LIKE: %s", term, e)
                    self._record_degradation("bm25_search", str(e), "Falling back to LIKE query")
                    try:
                        hits = self._like_search(term, repo_id, limit=30)
                    except Exception as like_e:
                        logger.warning("LIKE fallback also failed: %s", like_e)

            all_hits.extend(hits)

        return self._fuse_multiple(all_hits)

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

        root_entry = SymbolEntry(
            id=str(root.id),
            name=root.name,
            type=root.type,
            file_path=root.file.path if root.file else "",
            line=root.line,
        )

        upstream = []
        downstream = []

        if include_callers:
            caller_ids = self._query_callers(root_symbol_id, depth)
            for cid in caller_ids:
                sym = self.db.query(Symbol).filter(Symbol.id == cid).first()
                if sym:
                    upstream.append(SymbolEntry(
                        id=str(sym.id),
                        name=sym.name,
                        type=sym.type,
                        file_path=sym.file.path if sym.file else "",
                        line=sym.line,
                    ))

        if include_callees:
            callee_ids = self._query_callees(root_symbol_id, depth)
            for cid in callee_ids:
                sym = self.db.query(Symbol).filter(Symbol.id == cid).first()
                if sym:
                    downstream.append(SymbolEntry(
                        id=str(sym.id),
                        name=sym.name,
                        type=sym.type,
                        file_path=sym.file.path if sym.file else "",
                        line=sym.line,
                    ))

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
        path_lower = file_path.lower()
        name = file_path.split("/")[-1].lower()

        if "test" in path_lower or "spec" in name:
            return "test"
        if "controller" in name or "handler" in name or "route" in name:
            return "controller"
        if "service" in name or "biz" in name or "business" in name:
            return "service"
        if "repository" in name or "dao" in name or "mapper" in name or "data" in name:
            return "repository"
        if "config" in name or "settings" in name or "properties" in name:
            return "config"
        if "model" in name or "entity" in name or "domain" in name or "po" in name:
            return "model"
        if "util" in name or "helper" in name or "common" in name:
            return "utility"
        if "middleware" in name or "interceptor" in name or "filter" in name:
            return "middleware"
        return "other"

    def _fuse_multiple(self, hits: List[_Hit]) -> List[_Hit]:
        by_id: Dict[UUID, _Hit] = {}

        for hit in hits:
            if hit.result_id in by_id:
                existing = by_id[hit.result_id]
                existing.vector_score = max(existing.vector_score, hit.vector_score)
                existing.symbol_score = max(existing.symbol_score, hit.symbol_score)
                existing.bm25_score = max(existing.bm25_score, hit.bm25_score)
                existing.graph_score = max(existing.graph_score, hit.graph_score)
                existing.sources.update(hit.sources)
            else:
                by_id[hit.result_id] = hit

        return list(by_id.values())

    def hybrid_search(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
    ) -> List[SearchResultItem]:
        logger.info("Hybrid search query=%s repo_id=%s", query, repo_id)

        self._degraded_components = set()
        self._degradation_reasons = []

        self.db.execute(text("SET hnsw.ef_search = 128"))

        vector_results: List[_Hit] = []
        symbol_results: List[_Hit] = []
        bm25_results: List[_Hit] = []
        graph_results: List[_Hit] = []
        sparse_results: List[_Hit] = []

        try:
            query_embedding = self.embedder.encode_query(query)
            vector_results = self._vector_search(query_embedding, repo_id)
        except Exception as e:
            logger.warning("Vector search degraded: %s", e)
            self._record_degradation("vector_search", str(e), "Skipping vector search")

        try:
            query_sparse = self.embedder.encode_query_sparse(query)
            sparse_results = self._sparse_search(query_sparse, repo_id)
        except Exception as e:
            logger.warning("Sparse search degraded: %s", e)
            self._record_degradation("sparse_search", str(e), "Skipping sparse search")

        try:
            symbol_results = self._symbol_search(query, repo_id)
        except Exception as e:
            logger.warning("Symbol search degraded: %s", e)
            self._record_degradation("symbol_search", str(e), "Skipping symbol search")

        try:
            bm25_results = self._bm25_search(query, repo_id)
        except Exception as e:
            logger.warning("BM25 search degraded, falling back to LIKE: %s", e)
            self._record_degradation("bm25_search", str(e), "Falling back to LIKE query")
            try:
                bm25_results = self._like_search(query, repo_id)
            except Exception as like_e:
                logger.warning("LIKE fallback also failed: %s", like_e)

        try:
            if symbol_results:
                graph_results = self._graph_search(symbol_results, repo_id)
        except Exception as e:
            logger.warning("Graph search degraded: %s", e)
            self._record_degradation("graph_search", str(e), "Skipping graph search")

        results_by_source = {
            "vector": vector_results,
            "sparse": sparse_results,
            "symbol": symbol_results,
            "bm25": bm25_results,
            "graph": graph_results,
        }
        hits = _rrf_fuse(results_by_source)

        schema_results = [self._to_schema(hit) for hit in hits[:limit * 2]]
        reranked = CodeReranker().rerank(query, schema_results)

        m3_reranker = get_m3_reranker()
        final = m3_reranker.rerank(query, reranked[:limit * 2], top_k=limit)

        return final

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
            if SymbolNormalizer.match(query, sym.name):
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

    def _bm25_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        sql = text(
            """
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
                       ts_rank_cd(to_tsvector('simple', e.content), plainto_tsquery('simple', :query))
                   ) AS rank
            FROM embeddings e
            JOIN code_files f ON f.id = e.file_id
            JOIN repositories r ON r.id = e.repo_id
            WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
              AND (
                  to_tsvector('english', e.content) @@ plainto_tsquery('english', :query)
                  OR to_tsvector('simple', e.content) @@ plainto_tsquery('simple', :query)
              )
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            sql,
            {
                "query": query,
                "repo_id": str(repo_id) if repo_id else None,
                "limit": top_k,
            },
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

    def _like_search(
        self,
        query: str,
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        sql = text(
            """
            SELECT e.id AS embedding_id,
                   e.file_id,
                   e.repo_id,
                   r.name AS repo_name,
                   e.content,
                   e.start_line,
                   e.end_line,
                   f.path AS file_path,
                   f.language,
                   LENGTH(e.content) AS length
            FROM embeddings e
            JOIN code_files f ON f.id = e.file_id
            JOIN repositories r ON r.id = e.repo_id
            WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
              AND e.content LIKE :pattern
            ORDER BY length ASC
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            sql,
            {
                "pattern": f"%{query}%",
                "repo_id": str(repo_id) if repo_id else None,
                "limit": top_k,
            },
        ).fetchall()

        hits: List[_Hit] = []
        for row in rows:
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
                    bm25_score=0.3,
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

        symbol_ids = [h.result_id for h in symbol_hits if h.sources == {"symbol"}]
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
                file_path=emb.file_path,
                language=emb.file.language if emb.file else "",
                content=emb.content,
                line=emb.start_line,
                sparse_score=score,
                sources={"sparse"},
            ))
        return hits

    def _fuse(
        self,
        vector_results: List[_Hit],
        symbol_results: List[_Hit],
        bm25_results: List[_Hit],
        graph_results: List[_Hit],
    ) -> List[_Hit]:
        by_id: Dict[UUID, _Hit] = {}

        def merge(hit: _Hit, source_score_attr: str) -> _Hit:
            existing = by_id.get(hit.result_id)
            if existing:
                setattr(existing, source_score_attr, max(getattr(existing, source_score_attr), getattr(hit, source_score_attr)))
                existing.sources.update(hit.sources)
                return existing
            by_id[hit.result_id] = hit
            return hit

        for hit in vector_results:
            merge(hit, "vector_score")
        for hit in symbol_results:
            merge(hit, "symbol_score")
        for hit in bm25_results:
            merge(hit, "bm25_score")
        for hit in graph_results:
            merge(hit, "graph_score")

        hits = list(by_id.values())
        for attr in ("vector_score", "symbol_score", "bm25_score", "graph_score"):
            scores = [getattr(h, attr) for h in hits]
            normalized = _min_max_normalize(scores)
            for hit, norm in zip(hits, normalized):
                setattr(hit, attr, norm)

        return hits

    def _final_score(self, hit: _Hit) -> float:
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
        )


from repositories import EmbeddingRepository, SymbolRepository