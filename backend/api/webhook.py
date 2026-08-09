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


def _verify_github_signature(payload: bytes, signature: Optional[str], secret: Optional[str] = None) -> bool:
    """校验 GitHub X-Hub-Signature-256（HMAC-SHA256）。secret 缺省时用全局配置，未配置则免校验。"""
    secret = secret or settings.github_webhook_secret
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_gitee_token(x_gitee_token: Optional[str], token: Optional[str] = None) -> bool:
    """校验 Gitee X-Gitee-Token。token 缺省时用全局配置，未配置则免校验。"""
    token = token or settings.gitee_webhook_token
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

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

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

    # 验签：仓库级 webhook_token 优先；未配置则回退全局密钥
    repo_token = getattr(repo, "webhook_token", None)
    if repo_token:
        if x_gitee_token:
            if not _verify_gitee_token(x_gitee_token, repo_token):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid gitee token")
            event_type = (x_gitee_event or "push").lower()
        else:
            if not _verify_github_signature(payload, x_hub_signature_256, repo_token):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
            event_type = (request.headers.get("x-github-event") or "push").lower()
    else:
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

    active_branches = json.loads(repo.active_branches or "[]") or []
    is_main_branch = branch in ("main", "master")
    is_active_branch = branch in active_branches
    if not is_main_branch and not is_active_branch:
        logger.info("Ignoring push to branch %s (not main/master, not configured active branch)", branch)
        return {"status": "ignored", "reason": f"branch {branch} not main/master or active"}

    background_tasks.add_task(_sync_repo_branches, repo.id, "webhook")
    logger.info("Webhook triggered branch sync for repo %s (branch %s)", repo.id, branch)
    return {"status": "accepted", "repo_id": str(repo.id)}


@router.post("/webhook/github/{repo_id}", status_code=status.HTTP_202_ACCEPTED)
@router.post("/webhook/gitee/{repo_id}", status_code=status.HTTP_202_ACCEPTED)
async def repo_webhook_by_id(
    repo_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None),
    x_gitee_token: Optional[str] = Header(None),
    x_gitee_event: Optional[str] = Header(None),
) -> dict:
    """仓库级 Webhook 回调（GitHub / Gitee 共用）。

    按仓库平台返回 /webhook/github/{repo_id} 或 /webhook/gitee/{repo_id}，
    两个路径指向同一处理逻辑，通过请求头区分平台验签。
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    payload = await request.body()

    # 验签：仓库级 webhook_token 优先；未配置则回退全局密钥
    repo_token = getattr(repo, "webhook_token", None)
    if x_gitee_token:
        if not _verify_gitee_token(x_gitee_token, repo_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid gitee token")
        event_type = (x_gitee_event or "push").lower()
    else:
        if not _verify_github_signature(payload, x_hub_signature_256, repo_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
        event_type = (request.headers.get("x-github-event") or "push").lower()

    if event_type != "push":
        return {"status": "ignored", "event": event_type}

    # GitHub 默认以 application/x-www-form-urlencoded 发送，payload 在 form 的 payload 字段中；
    # Gitee 直接发送 application/json body。解析时兼容两种格式。
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        raw_payload = form.get("payload")
        if raw_payload is None:
            raise HTTPException(status_code=400, detail="Missing payload field")
        raw_payload = raw_payload.encode() if isinstance(raw_payload, str) else raw_payload
    else:
        raw_payload = payload
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    ref = data.get("ref", "")
    branch = ref.removeprefix("refs/heads/")
    if not branch:
        return {"status": "ignored", "reason": f"ref {ref} is not a branch push"}

    active_branches = json.loads(repo.active_branches or "[]") or []
    is_main_branch = branch in ("main", "master")
    is_active_branch = branch in active_branches
    if not is_main_branch and not is_active_branch:
        return {"status": "ignored", "reason": f"branch {branch} not main/master or active"}

    background_tasks.add_task(_sync_repo_branches, repo.id, "webhook")
    logger.info("Webhook triggered branch sync for repo %s (branch %s)", repo.id, branch)
    return {"status": "accepted", "repo_id": str(repo_id)}
