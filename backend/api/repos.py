"""Repository management endpoints."""

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import CodeFile, RepoStatus, Repository, Symbol
from schemas import RepoCreate, RepoResponse
from services.indexer import index_repo
from services.repo_sync import is_valid_git_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/repos", tags=["repos"])


def _repo_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")


def _attach_counts(db: Session, repo: Repository) -> Repository:
    """Attach transient count attributes for Pydantic serialization."""
    repo.total_files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).count()
    repo.indexed_files = repo.total_files
    return repo


def _get_repo(db: Session, repo_id: UUID) -> Repository:
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise _repo_not_found()
    return repo


@router.post("", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
def create_repo(
    payload: RepoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Repository:
    if not is_valid_git_url(payload.git_url):
        raise HTTPException(status_code=400, detail="Invalid git URL")

    existing = db.query(Repository).filter(Repository.git_url == payload.git_url).first()
    if existing:
        raise HTTPException(status_code=409, detail="Repository already exists")

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in payload.name).lower()
    repo = Repository(
        name=payload.name,
        git_url=payload.git_url,
        local_path=str(settings.repos_dir / safe_name),
        status=RepoStatus.pending.value,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Trigger initial indexing in background.
    background_tasks.add_task(index_repo, repo.id)
    logger.info("Created repository %s and scheduled indexing", repo.id)
    return _attach_counts(db, repo)


@router.get("", response_model=List[RepoResponse])
def list_repos(db: Session = Depends(get_db)) -> List[Repository]:
    repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
    return [_attach_counts(db, r) for r in repos]


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repo(repo_id: UUID, db: Session = Depends(get_db)) -> Repository:
    repo = _get_repo(db, repo_id)
    return _attach_counts(db, repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repo(repo_id: UUID, db: Session = Depends(get_db)) -> None:
    repo = _get_repo(db, repo_id)
    db.delete(repo)
    db.commit()
    logger.info("Deleted repository %s", repo_id)


@router.post("/{repo_id}/index", status_code=status.HTTP_202_ACCEPTED)
async def trigger_index(
    repo_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    repo = _get_repo(db, repo_id)
    background_tasks.add_task(index_repo, repo.id)
    return {"status": "indexing", "repo_id": str(repo_id)}


@router.get("/{repo_id}/files")
def list_repo_files(repo_id: UUID, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    repo = _get_repo(db, repo_id)
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).order_by(CodeFile.path).all()
    return [
        {
            "id": str(f.id),
            "path": f.path,
            "language": f.language,
            "size_bytes": f.size_bytes,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }
        for f in files
    ]


@router.get("/{repo_id}/symbols")
def list_repo_symbols(
    repo_id: UUID,
    file_path: str | None = None,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    repo = _get_repo(db, repo_id)
    q = db.query(Symbol).filter(Symbol.repo_id == repo.id)
    if file_path:
        file = db.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == file_path).first()
        if file:
            q = q.filter(Symbol.file_id == file.id)
    symbols = q.order_by(Symbol.line).all()
    return [
        {
            "id": str(s.id),
            "file_id": str(s.file_id),
            "name": s.name,
            "type": s.type,
            "kind": s.kind,
            "line": s.line,
            "column": s.column,
            "end_line": s.end_line,
            "is_exported": bool(s.is_exported),
        }
        for s in symbols
    ]
