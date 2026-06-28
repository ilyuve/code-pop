"""Repository for Repository model."""

from typing import List, Optional
from uuid import UUID

from models import Repository
from repositories.base import BaseRepository


class RepoRepository(BaseRepository):
    def get_by_id(self, repo_id: UUID) -> Optional[Repository]:
        return self.db.query(Repository).filter(Repository.id == repo_id).first()

    def get_by_git_url(self, git_url: str) -> Optional[Repository]:
        return self.db.query(Repository).filter(Repository.git_url == git_url).first()

    def list_all(self) -> List[Repository]:
        return self.db.query(Repository).order_by(Repository.created_at.desc()).all()

    def create(self, **kwargs) -> Repository:
        repo = Repository(**kwargs)
        self.db.add(repo)
        self.db.commit()
        self.db.refresh(repo)
        return repo

    def delete(self, repo: Repository) -> None:
        self.db.delete(repo)
        self.db.commit()
