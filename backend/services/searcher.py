"""Hybrid search engine: vector + symbol + BM25 + call graph fusion."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from models import CallGraphEdge, CodeFile, Embedding, Symbol
from schemas import SearchResultItem
from services.embedder import Embedder

logger = logging.getLogger(__name__)

# Fusion weights aligned with product spec.
WEIGHT_VECTOR = 0.4
WEIGHT_SYMBOL = 0.3
WEIGHT_BM25 = 0.2
WEIGHT_GRAPH = 0.1
BONUS_VECTOR_SYMBOL = 0.1


def _min_max_normalize(scores: List[float]) -> List[float]:
    """Normalize scores to [0, 1] using min-max scaling."""
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
    sources: set = field(default_factory=set)


def _symbol_to_hit(symbol: Symbol, embeddings: List[Embedding]) -> _Hit:
    """Map a symbol result to a hit, preferring an embedding chunk covering the symbol line."""
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
            )
    # Fallback: symbol only, no chunk coverage.
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
    )


class Searcher:
    """Hybrid code search over pgvector, symbols, full text and call graph."""

    def __init__(self, db: Session):
        self.db = db
        self.embedder = Embedder()

    def hybrid_search(
        self,
        query: str,
        repo_id: Optional[UUID] = None,
        limit: int = 20,
    ) -> List[SearchResultItem]:
        logger.info("Hybrid search query=%s repo_id=%s", query, repo_id)

        query_embedding = self.embedder.encode_query(query)

        vector_results = self._vector_search(query_embedding, repo_id)
        symbol_results = self._symbol_search(query, repo_id)
        bm25_results = self._bm25_search(query, repo_id)
        graph_results = self._graph_search(symbol_results, repo_id)

        hits = self._fuse(vector_results, symbol_results, bm25_results, graph_results)
        hits.sort(key=lambda h: self._final_score(h), reverse=True)

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

    # ------------------------------------------------------------------
    # Recall paths
    # ------------------------------------------------------------------

    def _vector_search(
        self,
        query_embedding: List[float],
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
                   e.embedding <=> (:embedding)::vector AS distance
            FROM embeddings e
            JOIN code_files f ON f.id = e.file_id
            JOIN repositories r ON r.id = e.repo_id
            WHERE (:repo_id IS NULL OR e.repo_id = :repo_id)
            ORDER BY e.embedding <=> (:embedding)::vector
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            sql,
            {
                "embedding": query_embedding,
                "repo_id": str(repo_id) if repo_id else None,
                "limit": top_k,
            },
        ).fetchall()

        hits: List[_Hit] = []
        for row in rows:
            distance = row.distance
            if isinstance(distance, str):
                distance = float(distance)
            score = max(0.0, 1.0 - distance)
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
        q = self.db.query(Symbol).join(CodeFile, Symbol.file_id == CodeFile.id)
        if repo_id:
            q = q.filter(Symbol.repo_id == repo_id)

        prefix = query.lower()
        exact = q.filter(Symbol.name == query).all()
        prefix_matches = (
            q.filter(Symbol.name.ilike(f"{prefix}%"))
            .filter(Symbol.name != query)
            .limit(limit)
            .all()
        )
        contains_matches = (
            q.filter(Symbol.name.ilike(f"%{prefix}%"))
            .filter(~Symbol.name.ilike(f"{prefix}%"))
            .limit(limit)
            .all()
        )

        seen: set = set()
        results: List[Symbol] = []
        for sym in exact + prefix_matches + contains_matches:
            if sym.id in seen:
                continue
            seen.add(sym.id)
            results.append(sym)
            if len(results) >= limit:
                break
        return results

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
            # Score by match quality: exact > prefix > contains.
            if sym.name == query:
                hit.symbol_score = 1.0
            elif sym.name.lower().startswith(query.lower()):
                hit.symbol_score = 0.8
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
        # Use PostgreSQL full-text ranking. Try english then simple for code mixed text.
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

    def _graph_search(
        self,
        symbol_hits: List[_Hit],
        repo_id: Optional[UUID],
        top_k: int = 50,
    ) -> List[_Hit]:
        if not symbol_hits:
            return []

        symbol_ids = {h.result_id for h in symbol_hits if h.sources == {"symbol"}}
        if not symbol_ids:
            # Symbol hits may have been mapped to embeddings; fall back to file ids.
            file_ids = {h.file_id for h in symbol_hits}
            related_symbols = (
                self.db.query(Symbol)
                .filter(Symbol.file_id.in_(file_ids))
                .limit(top_k)
                .all()
            )
        else:
            edges = (
                self.db.query(CallGraphEdge)
                .filter(
                    (CallGraphEdge.source_symbol_id.in_(symbol_ids))
                    | (CallGraphEdge.target_symbol_id.in_(symbol_ids))
                )
                .limit(top_k * 2)
                .all()
            )
            related_ids: set = set()
            for edge in edges:
                related_ids.add(edge.source_symbol_id)
                related_ids.add(edge.target_symbol_id)
            related_symbols = (
                self.db.query(Symbol).filter(Symbol.id.in_(related_ids)).limit(top_k).all()
            )

        hits: List[_Hit] = []
        for sym in related_symbols:
            embeddings = self._file_embeddings(sym.file_id)
            hit = _symbol_to_hit(sym, embeddings)
            hit.graph_score = 0.7
            hit.sources.add("graph")
            hits.append(hit)
        return hits

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _file_embeddings(self, file_id: UUID) -> List[Embedding]:
        return (
            self.db.query(Embedding)
            .filter(Embedding.file_id == file_id)
            .order_by(Embedding.start_line)
            .all()
        )

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

        # Normalize each signal across the candidate pool.
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
        )
        if "vector" in hit.sources and "symbol" in hit.sources:
            score += BONUS_VECTOR_SYMBOL
        return score

    def _to_schema(self, hit: _Hit) -> SearchResultItem:
        return SearchResultItem(
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
        )
