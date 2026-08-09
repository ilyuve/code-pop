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
from api.repos import _normalize_git_url
from services.repo_sync import _sync_repo_branches

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


def _verify_github_signature(payload: bytes, signature: Optional[str]) -> bool:
    """校验 GitHub X-Hub-Signature-256（HMAC-SHA256）。未配置 secret 时免校验。"""
    secret = settings.github_webhook_secret
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_gitee_token(x_gitee_token: Optional[str]) -> bool:
    """校验 Gitee X-Gitee-Token（WebHooks 配置里设置的密码）。未配置 token 时免校验。"""
    token = settings.gitee_webhook_token
    if not token:
        return True
    if not x_gitee_token:
        return False
    return hmac.compare_digest(token, x_gitee_token)


def _find_repo(db: Session, clone_url: str) -> Optional[Repository]:
    """按归一化 git 地址匹配仓库（容忍 .git 后缀/大小写差异）。

    GitHub/Gitee webhook 的 clone_url 通常带 .git，而仓库入库时可能不带，
    直接用精确相等会漏匹配，因此统一走归一化比较。
    """
    normalized = _normalize_git_url(clone_url)
    for repo in db.query(Repository).all():
        if repo.git_url and _normalize_git_url(repo.git_url) == normalized:
            return repo
    return None


@router.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None),
    x_gitee_token: Optional[str] = Header(None),
    x_gitee_event: Optional[str] = Header(None),
) -> dict:
    payload = await request.body()

    # GitHub 走 HMAC 签名校验；Gitee 走 X-Gitee-Token 校验（同一端点复用）。
    is_gitee = bool(x_gitee_token) or bool(x_gitee_event)
    if is_gitee:
        if not _verify_gitee_token(x_gitee_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid gitee token")
        event_type = (x_gitee_event or "push").lower()
    else:
        if not _verify_github_signature(payload, x_hub_signature_256):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
        event_type = (request.headers.get("x-github-event") or "push").lower()

    if event_type != "push":
        return {"status": "ignored", "event": event_type}

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    # 只处理 main / master 或该仓库已配置业务分支（active_branches）的 push
    ref = data.get("ref", "")
    branch = ref.removeprefix("refs/heads/")
    if not branch:
        logger.info("Ignoring non-branch ref %s", ref)
        return {"status": "ignored", "reason": f"ref {ref} is not a branch push"}

    repo_info = data.get("repository") or {}
    clone_url = repo_info.get("clone_url")
    if not clone_url:
        raise HTTPException(status_code=400, detail="Missing repository.clone_url")

    repo = _find_repo(db, clone_url)
    if not repo:
        logger.warning("Webhook received for unknown repository: %s", clone_url)
        return {"status": "ignored", "reason": "repository not registered"}

    active_branches = json.loads(repo.active_branches or "[]") or []
    is_main_branch = branch in ("main", "master")
    is_active_branch = branch in active_branches
    if not is_main_branch and not is_active_branch:
        logger.info("Ignoring push to branch %s (not main/master, not configured active branch)", branch)
        return {"status": "ignored", "reason": f"branch {branch} not main/master or active"}

    background_tasks.add_task(_sync_repo_branches, repo.id)
    logger.info("Webhook triggered branch sync for repo %s (branch %s)", repo.id, branch)
    return {"status": "accepted", "repo_id": str(repo.id)}


@router.post("/webhook/github/{repo_id}", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook_by_repo_id(
    repo_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None),
    x_gitee_token: Optional[str] = Header(None),
) -> dict:
    """Alternative webhook URL that triggers indexing for a known repo_id."""
    payload = await request.body()

    if x_gitee_token:
        if not _verify_gitee_token(x_gitee_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid gitee token")
    elif not _verify_github_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    background_tasks.add_task(_sync_repo_branches, repo.id)
    return {"status": "accepted", "repo_id": str(repo_id)}
