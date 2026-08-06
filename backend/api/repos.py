"""Repository management endpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from exceptions import RepoAlreadyExistsException, RepoNotFoundException, ValidationException
from models import CodeFile, RepoStatus, Repository, Symbol
from schemas import RepoCreate, RepoResponse
from services.indexer import index_repo, _get_indexing_logs, _cancel_indexing, _clear_indexing_logs, _clear_indexing_state
from models import DomainSynonym, FrameworkRoute, IndexingLog, IndexingProgress, LlmSetting
from services.repo_sync import is_valid_git_url

logger = logging.getLogger(__name__)


def _format_dt(dt: Optional[datetime]) -> Optional[str]:
    """Format a naive UTC datetime as ISO 8601 with explicit +00:00 offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


router = APIRouter(prefix="/api/repos", tags=["repos"])


def _attach_counts(db: Session, repo: Repository) -> Repository:
    """Attach transient count attributes for Pydantic serialization."""
    repo.total_files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).count()
    repo.indexed_files = repo.total_files
    return repo


def _get_repo(db: Session, repo_id: UUID) -> Repository:
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise RepoNotFoundException(str(repo_id))
    return repo


@router.post("", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
def create_repo(
    payload: RepoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Repository:
    if not payload.git_url and not payload.path:
        raise ValidationException("Must provide either git_url or path")

    if payload.git_url and not is_valid_git_url(payload.git_url):
        raise ValidationException("Invalid git URL")

    if payload.git_url:
        existing = db.query(Repository).filter(Repository.git_url == payload.git_url).first()
        if existing:
            raise RepoAlreadyExistsException(payload.git_url)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in payload.name).lower()
        local_path = str(settings.repos_dir / safe_name)
    else:
        existing = db.query(Repository).filter(Repository.local_path == payload.path).first()
        if existing:
            raise RepoAlreadyExistsException(payload.path)
        local_path = payload.path

    repo = Repository(
        name=payload.name,
        git_url=payload.git_url or "",
        local_path=local_path,
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
    repo_id_str = str(repo_id)

    # Cancel any running indexing task first so it doesn't keep writing to the
    # database while we are trying to delete the repository.
    if repo.status == RepoStatus.indexing.value:
        _cancel_indexing(repo_id_str)

    try:
        # Explicitly clean up related records first.  This avoids subtle FK
        # ordering issues and makes deletion work even if SQLAlchemy cascade
        # relationships are not fully loaded.
        db.query(IndexingProgress).filter(IndexingProgress.repo_id == repo_id).delete(synchronize_session=False)
        db.query(IndexingLog).filter(IndexingLog.repo_id == repo_id).delete(synchronize_session=False)
        db.query(FrameworkRoute).filter(FrameworkRoute.repo_id == repo_id).delete(synchronize_session=False)
        db.query(DomainSynonym).filter(DomainSynonym.repo_id == repo_id).delete(synchronize_session=False)
        db.query(LlmSetting).filter(LlmSetting.repo_id == repo_id).delete(synchronize_session=False)

        db.delete(repo)
        db.commit()

        # Clean up in-memory indexing state as well.
        _clear_indexing_logs(repo_id_str)
        _clear_indexing_state(repo_id_str)
        logger.info("Deleted repository %s", repo_id)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to delete repository %s: %s", repo_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete repository: {str(exc)}",
        )


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
            "updated_at": _format_dt(f.updated_at),
        }
        for f in files
    ]


@router.get("/{repo_id}/symbols")
def list_repo_symbols(
    repo_id: UUID,
    file_path: Optional[str] = None,
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


@router.get("/{repo_id}/logs")
def get_indexing_logs(repo_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    repo_id_str = str(repo_id)
    in_memory_logs = _get_indexing_logs(repo_id_str)
    
    db_logs = db.query(IndexingLog).filter(
        IndexingLog.repo_id == repo_id
    ).order_by(IndexingLog.created_at).all()
    
    db_logs_list = [
        {
            "timestamp": _format_dt(log.created_at),
            "level": log.level,
            "message": log.message,
            "stage": log.stage,
        }
        for log in db_logs
    ]
    
    seen = set()
    all_logs = []
    for log in db_logs_list + in_memory_logs:
        ts = log["timestamp"]
        if isinstance(ts, datetime):
            ts = _format_dt(ts)
            log = {**log, "timestamp": ts}
        key = f"{ts}-{log['message']}"
        if key not in seen:
            seen.add(key)
            all_logs.append(log)
    
    return {
        "repo_id": repo_id_str,
        "logs": sorted(all_logs, key=lambda x: x["timestamp"]),
        "count": len(all_logs),
    }


@router.get("/{repo_id}/progress")
def get_indexing_progress(repo_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    repo = _get_repo(db, repo_id)
    
    stages = db.query(IndexingProgress).filter(
        IndexingProgress.repo_id == repo_id
    ).order_by(IndexingProgress.created_at).all()
    
    stage_progress = {
        stage.stage: {
            "progress": stage.progress,
            "current": stage.current,
            "total": stage.total,
            "status": stage.status,
            "message": stage.message,
        }
        for stage in stages
    }
    
    current_stage = None
    overall_progress = 0
    if stages:
        latest_stages = {}
        for stage in stages:
            latest_stages[stage.stage] = stage
        
        # Actual execution order: git_sync -> scan -> chinese_enrichment -> symbols -> embeddings -> flow_labels -> call_graph
        stage_order = ["git_sync", "scan", "chinese_enrichment", "symbols", "embeddings", "flow_labels", "call_graph"]
        
        # The current stage is the last stage in order that has any progress record.
        for stage_name in stage_order:
            if stage_name in latest_stages:
                current_stage = stage_name
        
        if current_stage:
            overall_progress = latest_stages[current_stage].progress
    
    elapsed_seconds: Optional[float] = None
    estimated_remaining_seconds: Optional[float] = None
    if repo.indexing_started_at and repo.status == RepoStatus.indexing.value:
        started_at = repo.indexing_started_at
        if started_at.tzinfo is not None:
            started_at = started_at.replace(tzinfo=None)
        elapsed_seconds = (datetime.utcnow() - started_at).total_seconds()
        if 0 < overall_progress < 100:
            estimated_remaining_seconds = elapsed_seconds * (100 - overall_progress) / overall_progress
    
    return {
        "repo_id": str(repo_id),
        "status": repo.status,
        "overall_progress": round(overall_progress, 2),
        "current_stage": current_stage,
        "stage_progress": stage_progress,
        "last_indexed_at": _format_dt(repo.last_indexed_at),
        "indexing_started_at": _format_dt(repo.indexing_started_at),
        "elapsed_seconds": round(elapsed_seconds, 2) if elapsed_seconds is not None else None,
        "estimated_remaining_seconds": round(estimated_remaining_seconds, 2) if estimated_remaining_seconds is not None else None,
    }


@router.post("/{repo_id}/cancel")
def cancel_indexing(repo_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    repo = _get_repo(db, repo_id)
    repo_id_str = str(repo_id)
    cancelled = _cancel_indexing(repo_id_str)
    
    if cancelled:
        repo.status = RepoStatus.pending.value
        db.commit()
        return {"status": "cancelled", "repo_id": repo_id_str}
    
    return {"status": "not_running", "repo_id": repo_id_str}
