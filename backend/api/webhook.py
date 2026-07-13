"""GitHub webhook endpoint."""

import hashlib
import hmac
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Repository
from services.indexer import index_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


def _verify_signature(payload: bytes, signature: Optional[str]) -> bool:
    secret = settings.github_webhook_secret
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _find_repo(db: Session, clone_url: str) -> Optional[Repository]:
    return db.query(Repository).filter(Repository.git_url == clone_url).first()


@router.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None),
) -> dict:
    payload = await request.body()
    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event_type = request.headers.get("x-github-event", "push")
    if event_type != "push":
        return {"status": "ignored", "event": event_type}

    repo_info = data.get("repository") or {}
    clone_url = repo_info.get("clone_url")
    if not clone_url:
        raise HTTPException(status_code=400, detail="Missing repository.clone_url")

    repo = _find_repo(db, clone_url)
    if not repo:
        logger.warning("Webhook received for unknown repository: %s", clone_url)
        return {"status": "ignored", "reason": "repository not registered"}

    background_tasks.add_task(index_repo, repo.id)
    logger.info("Webhook triggered re-index for repo %s", repo.id)
    return {"status": "accepted", "repo_id": str(repo.id)}


@router.post("/webhook/github/{repo_id}", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook_by_repo_id(
    repo_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None),
) -> dict:
    """Alternative webhook URL that triggers indexing for a known repo_id."""
    payload = await request.body()
    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    background_tasks.add_task(index_repo, repo.id)
    return {"status": "accepted", "repo_id": str(repo_id)}
