"""Repository for CodeFile model."""

from typing import List, Optional
from uuid import UUID

from models import CodeFile
from repositories.base import BaseRepository


class CodeFileRepository(BaseRepository):
    def get_by_id(self, file_id: UUID) -> Optional[CodeFile]:
        return self.db.query(CodeFile).filter(CodeFile.id == file_id).first()

    def get_by_path(self, repo_id: UUID, path: str) -> Optional[CodeFile]:
        return (
            self.db.query(CodeFile)
            .filter(CodeFile.repo_id == repo_id, CodeFile.path == path)
            .first()
        )

    def list_by_repo(self, repo_id: UUID) -> List[CodeFile]:
        return self.db.query(CodeFile).filter(CodeFile.repo_id == repo_id).all()

    def delete_by_repo(self, repo_id: UUID) -> int:
        return (
            self.db.query(CodeFile)
            .filter(CodeFile.repo_id == repo_id)
            .delete(synchronize_session=False)
        )
