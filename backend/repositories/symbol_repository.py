"""Repository for Symbol model."""

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import or_

from models import CodeFile, Symbol, SymbolFlowLabel
from repositories.base import BaseRepository


class SymbolRepository(BaseRepository):
    def get_by_id(self, symbol_id: UUID) -> Optional[Symbol]:
        return self.db.query(Symbol).filter(Symbol.id == symbol_id).first()

    def get_by_file_id(self, file_id: UUID) -> List[Symbol]:
        return (
            self.db.query(Symbol)
            .filter(Symbol.file_id == file_id)
            .order_by(Symbol.line)
            .all()
        )

    def search_by_name(
        self, query: str, repo_id: Optional[UUID] = None, limit: int = 50
    ) -> List[Symbol]:
        prefix = query.lower()
        q = (
            self.db.query(Symbol)
            .join(CodeFile, Symbol.file_id == CodeFile.id)
            .outerjoin(SymbolFlowLabel, Symbol.id == SymbolFlowLabel.symbol_id)
        )
        if repo_id:
            q = q.filter(Symbol.repo_id == repo_id)

        scored_matches: List[tuple] = []

        def _add(matches, score: float) -> None:
            for sym in matches:
                scored_matches.append((sym, score))

        # Symbol name matches (primary).
        _add(q.filter(Symbol.name == query).all(), 1.0)
        _add(
            q.filter(Symbol.name.ilike(f"{prefix}%"))
            .filter(Symbol.name != query)
            .limit(limit)
            .all(),
            0.9,
        )
        _add(
            q.filter(Symbol.name.ilike(f"%{prefix}%"))
            .filter(~Symbol.name.ilike(f"{prefix}%"))
            .limit(limit)
            .all(),
            0.7,
        )

        # Chinese flow-label matches (secondary).
        _add(q.filter(SymbolFlowLabel.chinese_name == query).all(), 0.85)
        _add(
            q.filter(SymbolFlowLabel.chinese_name.ilike(f"%{prefix}%"))
            .limit(limit)
            .all(),
            0.6,
        )
        _add(
            q.filter(SymbolFlowLabel.io_description.ilike(f"%{prefix}%"))
            .limit(limit)
            .all(),
            0.4,
        )

        # Deduplicate and keep highest score per symbol.
        best_score: Dict[UUID, float] = {}
        for sym, score in scored_matches:
            if sym.id not in best_score or score > best_score[sym.id]:
                best_score[sym.id] = score

        sorted_ids = sorted(best_score.keys(), key=lambda sid: -best_score[sid])[:limit]
        symbols = self.get_by_ids(sorted_ids)
        for sym in symbols:
            sym._search_score = best_score[sym.id]
        return symbols

    def get_by_ids(self, symbol_ids: List[UUID]) -> List[Symbol]:
        if not symbol_ids:
            return []
        return self.db.query(Symbol).filter(Symbol.id.in_(symbol_ids)).all()

    def get_by_file_ids(self, file_ids: List[UUID], limit: int = 50) -> List[Symbol]:
        if not file_ids:
            return []
        return self.db.query(Symbol).filter(Symbol.file_id.in_(file_ids)).limit(limit).all()

    def get_related_by_edges(
        self, symbol_ids: List[UUID], limit: int = 50
    ) -> List[Symbol]:
        from models import CallGraphEdge

        if not symbol_ids:
            return []
        edges = (
            self.db.query(CallGraphEdge)
            .filter(
                or_(
                    CallGraphEdge.source_symbol_id.in_(symbol_ids),
                    CallGraphEdge.target_symbol_id.in_(symbol_ids),
                )
            )
            .limit(limit * 2)
            .all()
        )
        related_ids: set = set()
        for edge in edges:
            related_ids.add(edge.source_symbol_id)
            related_ids.add(edge.target_symbol_id)
        return self.get_by_ids(list(related_ids))[:limit]
