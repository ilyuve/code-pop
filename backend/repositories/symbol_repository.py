"""Repository for Symbol model."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_

from models import CodeFile, Symbol
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
