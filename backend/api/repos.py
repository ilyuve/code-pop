"""Repository management endpoints."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from exceptions import RepoAlreadyExistsException, RepoNotFoundException, ValidationException
from models import CodeFile, RepoStatus, Repository, Symbol
from schemas import RepoCreate, RepoResponse, RepoUpdate
from services.indexer import index_repo, _get_indexing_logs, _cancel_indexing, _clear_indexing_logs, _clear_indexing_state
from models import DomainSynonym, FrameworkRoute, IndexingLog, IndexingProgress, LlmSetting
from services.repo_sync import (
    get_repo_local_path,
    is_valid_git_url,
    preview_remote_branches,
    _sync_repo_branches,
)

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
async def create_repo(
    payload: RepoCreate,
    db: Session = Depends(get_db),
) -> Repository:
    if not payload.git_url and not payload.path:
        raise ValidationException("Must provide either git_url or path")

    if payload.git_url and not is_valid_git_url(payload.git_url):
        raise ValidationException("Invalid git URL")

    active_branches = payload.active_branches or []
    if len(active_branches) > 2:
        raise ValidationException("active_branches 最多 2 个")

    default_branch = "main"
    if payload.git_url:
        existing = db.query(Repository).filter(Repository.git_url == payload.git_url).first()
        if existing:
            raise RepoAlreadyExistsException(payload.git_url)
        try:
            preview = preview_remote_branches(payload.git_url)
            default_branch = preview.get("default_branch") or default_branch
        except Exception as exc:
            logger.warning("Failed to preview branches for %s: %s", payload.git_url, exc)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in payload.name).lower()
        local_path = str(settings.repos_dir / safe_name / default_branch)
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
        default_branch=default_branch,
        active_branches=json.dumps(active_branches) if active_branches else None,
        sync_mode=payload.sync_mode or "auto",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # Trigger initial sync in background (default branch + active business branches).
    import asyncio
    _fire_and_forget(_sync_repo_branches(repo.id))
    logger.info("Created repository %s and scheduled branch sync", repo.id)
    return _attach_counts(db, repo)


@router.get("", response_model=List[RepoResponse])
def list_repos(db: Session = Depends(get_db)) -> List[Repository]:
    repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
    return [_attach_counts(db, r) for r in repos]


@router.get("/branches/preview")
def preview_repo_branches(git_url: str) -> dict:
    """Preview remote branches and detected default branch for a git URL.

    Used by the create-repo form to render a branch dropdown.
    """
    if not is_valid_git_url(git_url):
        raise ValidationException("Invalid git URL")
    try:
        return preview_remote_branches(git_url)
    except Exception as exc:
        logger.warning("Failed to preview branches for %s: %s", git_url, exc)
        raise ValidationException(f"无法获取远程分支列表: {exc}")


@router.get("/{repo_id}/branches", response_model=dict)
def get_repo_branches(repo_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Return queryable branches for a repo (default branch first)."""
    repo = _get_repo(db, repo_id)
    active_branches = json.loads(repo.active_branches or "[]")
    active_branches = [b for b in active_branches if b != repo.default_branch]
    return {
        "default_branch": repo.default_branch,
        "active_branches": active_branches,
    }


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repo(repo_id: UUID, db: Session = Depends(get_db)) -> Repository:
    repo = _get_repo(db, repo_id)
    return _attach_counts(db, repo)


@router.patch("/{repo_id}", response_model=RepoResponse)
async def update_repo(
    repo_id: UUID,
    payload: RepoUpdate,
    db: Session = Depends(get_db),
) -> Repository:
    """Update repository configuration (active_branches / sync_mode).

    Changing active_branches triggers a background re-sync to rebuild
    branch diff indexes.
    """
    repo = _get_repo(db, repo_id)

    if payload.active_branches is not None:
        active_branches = payload.active_branches
        if len(active_branches) > 2:
            raise ValidationException("active_branches 最多 2 个")
        repo.active_branches = json.dumps(active_branches) if active_branches else None

    if payload.sync_mode is not None:
        repo.sync_mode = payload.sync_mode

    db.commit()
    db.refresh(repo)

    if payload.active_branches is not None:
        _fire_and_forget(_sync_repo_branches(repo.id))
        logger.info("Active branches changed for repo %s, scheduled sync", repo.id)

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


def _fire_and_forget(coro) -> None:
    """Schedule a coroutine as a background task and swallow unretrieved exceptions."""
    import asyncio
    task = asyncio.create_task(coro)
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


@router.post("/{repo_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    repo_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    repo = _get_repo(db, repo_id)
    _fire_and_forget(_sync_repo_branches(repo.id))
    return {"status": "syncing", "repo_id": str(repo_id)}


@router.get("/{repo_id}/files")
def list_repo_files(
    repo_id: UUID,
    branch: Optional[str] = "main",
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    repo = _get_repo(db, repo_id)
    files = (
        db.query(CodeFile)
        .filter(CodeFile.repo_id == repo.id, CodeFile.branch == branch)
        .order_by(CodeFile.path)
        .all()
    )
    return [
        {
            "id": str(f.id),
            "path": f.path,
            "language": f.language,
            "size_bytes": f.size_bytes,
            "updated_at": _format_dt(f.updated_at),
            "branch": f.branch,
        }
        for f in files
    ]


@router.get("/{repo_id}/symbols")
def list_repo_symbols(
    repo_id: UUID,
    file_path: Optional[str] = None,
    branch: Optional[str] = "main",
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    repo = _get_repo(db, repo_id)
    q = db.query(Symbol).filter(Symbol.repo_id == repo.id, Symbol.branch == branch)
    if file_path:
        file = (
            db.query(CodeFile)
            .filter(CodeFile.repo_id == repo.id, CodeFile.branch == branch, CodeFile.path == file_path)
            .first()
        )
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
            "branch": s.branch,
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
