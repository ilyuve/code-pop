"""Repository for Embedding model."""

from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from models import Embedding
from repositories.base import BaseRepository


class EmbeddingRepository(BaseRepository):
    def get_by_id(self, embedding_id: UUID) -> Optional[Embedding]:
        return self.db.query(Embedding).filter(Embedding.id == embedding_id).first()

    def get_by_file_id(self, file_id: UUID) -> List[Embedding]:
        return (
            self.db.query(Embedding)
            .filter(Embedding.file_id == file_id)
            .order_by(Embedding.start_line)
            .all()
        )

    def get_by_file_ids(self, file_ids: List[UUID]) -> Dict[UUID, List[Embedding]]:
        """Return embeddings grouped by file_id in a single query."""
        if not file_ids:
            return {}
        rows = (
            self.db.query(Embedding)
            .filter(Embedding.file_id.in_(file_ids))
            .order_by(Embedding.start_line)
            .all()
        )
        result: Dict[UUID, List[Embedding]] = {}
        for row in rows:
            result.setdefault(row.file_id, []).append(row)
        return result

    def vector_search(
        self,
        query_embedding: List[float],
        repo_id: Optional[UUID] = None,
        branch: str = "main",
        top_k: int = 50,
    ) -> List[dict]:
        """Return raw row dicts from pgvector cosine similarity search."""
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
              AND e.branch = :branch
            ORDER BY e.embedding <=> (:embedding)::vector
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            sql,
            {
                "embedding": query_embedding,
                "repo_id": str(repo_id) if repo_id else None,
                "branch": branch,
                "limit": top_k,
            },
        ).fetchall()
        return [dict(row._mapping) for row in rows]
