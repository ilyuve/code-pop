"""Git clone / pull / sync operations for repositories with branch support."""

import asyncio
import json
import logging
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

import redis

from config import settings
from models import RepoStatus

logger = logging.getLogger(__name__)

# In-process locks to dedupe concurrent syncs of the same repository within
# this backend instance. PostgreSQL advisory locks below provide cross-process
# protection; this asyncio lock avoids connection-bouncing issues across awaits.
_sync_locks: Dict[str, asyncio.Lock] = {}


class GitSyncError(Exception):
    """Custom exception for git sync errors with detailed message."""

    def __init__(self, message: str, command: str, stderr: str = ""):
        self.command = command
        self.stderr = stderr
        super().__init__(message)


def _safe_name(name: str) -> str:
    """Sanitize repository name for filesystem path."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()


def is_valid_git_url(url: str) -> bool:
    """Return True if the URL looks like a git remote."""
    if not url:
        return False
    return (
        url.startswith(("http://", "https://", "git@", "git://", "ssh://"))
        or url.endswith(".git")
    )


def _repo_local_path(name: str) -> Path:
    """Legacy root path for a repo (before branch-aware layout).

    Kept for backward compatibility. New code should use ``get_repo_local_path``.
    """
    return settings.repos_dir / _safe_name(name)


def get_repo_local_path(repo, branch: Optional[str] = None) -> str:
    """Return the local storage path for a given repo and branch.

    Layout: ``repos/{safe_name}/{branch}/``.
    If ``branch`` is omitted, ``repo.default_branch`` is used.
    """
    branch = branch or getattr(repo, "default_branch", "main")
    return str(settings.repos_dir / _safe_name(repo.name) / branch)


def migrate_legacy_repo_path(repo) -> str:
    """Migrate old ``repos/{safe_name}/`` layout to ``repos/{safe_name}/{default_branch}/``.

    Called at startup for each repository. The move is atomic (via a temp dir)
    and only runs when the new path does not yet exist.
    """
    safe_name = _safe_name(repo.name)
    legacy_path = settings.repos_dir / safe_name
    new_path = legacy_path / repo.default_branch

    if not legacy_path.exists() or new_path.exists():
        return str(new_path)

    # If legacy_path is already a git repo, move it into {default_branch}/
    if (legacy_path / ".git").is_dir():
        temp_path = settings.repos_dir / f"{safe_name}.migrate.tmp"
        logger.info("Migrating legacy repo path %s -> %s", legacy_path, new_path)
        shutil.move(str(legacy_path), str(temp_path))
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(new_path))
        logger.info("Migration complete: %s", new_path)
    else:
        # Ensure the new branch directory exists for fresh clones
        new_path.mkdir(parents=True, exist_ok=True)

    return str(new_path)


def fetch_branch(
    remote_url: str,
    local_path: str,
    branch: str,
    default_branch: Optional[str] = None,
) -> None:
    """Ensure ``local_path`` contains a shallow clone of ``branch``.

    For business branches, also fetch the ``default_branch`` ref so that
    ``index_repo`` can compute the diff against the baseline.
    """
    path = Path(local_path)
    path.mkdir(parents=True, exist_ok=True)

    def _set_http_version() -> None:
        # Force HTTP/1.1 to avoid HTTP2 framing layer errors in restricted networks.
        try:
            _run_git(
                ["git", "-C", str(path), "config", "http.version", "HTTP/1.1"],
                command_desc="git config http.version",
                timeout=30,
            )
        except GitSyncError:
            logger.warning("Failed to set http.version for %s", local_path)

    if not (path / ".git").exists():
        logger.info("Cloning branch %s into %s", branch, local_path)
        _run_git(
            ["git", "clone", "--depth", "1", "--branch", branch, remote_url, str(path)],
            command_desc=f"git clone --branch {branch}",
            timeout=300,
        )
        _set_http_version()
    else:
        logger.info("Fetching branch %s at %s", branch, local_path)
        _set_http_version()
        # Ensure a clean working tree before fetch/checkout to avoid
        # "local changes would be overwritten" errors on subsequent syncs.
        try:
            _run_git(
                ["git", "-C", str(path), "reset", "--hard"],
                command_desc="git reset --hard",
                timeout=60,
            )
            _run_git(
                ["git", "-C", str(path), "clean", "-fd"],
                command_desc="git clean -fd",
                timeout=60,
            )
        except GitSyncError:
            logger.warning("Failed to clean working tree for %s, continuing", local_path)
        try:
            _run_git(
                ["git", "-C", str(path), "fetch", "origin", branch],
                command_desc="git fetch",
                timeout=300,
            )
            _run_git(
                ["git", "-C", str(path), "checkout", "-B", branch, f"origin/{branch}"],
                command_desc="git checkout",
                timeout=60,
            )
        except GitSyncError as fetch_exc:
            # If remote is unreachable but we already have a local checkout,
            # continue with the existing code so offline / restricted-network
            # environments can still index local data.
            logger.warning(
                "Remote fetch failed for %s branch %s, continuing with local checkout: %s",
                local_path, branch, fetch_exc
            )
            try:
                _run_git(
                    ["git", "-C", str(path), "checkout", branch],
                    command_desc="git checkout local",
                    timeout=60,
                )
            except GitSyncError:
                logger.warning("Local checkout of %s failed, continuing with current HEAD", branch)

    if default_branch and default_branch != branch:
        try:
            # Use an explicit refspec so the baseline lands in a remote-tracking
            # ref (origin/{default_branch}); a plain "git fetch origin <branch>"
            # would only update FETCH_HEAD when remote.origin.fetch does not
            # match the requested branch.
            _run_git(
                [
                    "git", "-C", str(path), "fetch", "origin",
                    f"+refs/heads/{default_branch}:refs/remotes/origin/{default_branch}",
                ],
                command_desc=f"git fetch baseline {default_branch}",
                timeout=300,
            )
        except GitSyncError as baseline_exc:
            logger.warning(
                "Baseline fetch failed for %s branch %s: %s",
                local_path, default_branch, baseline_exc
            )


def _get_current_commit(local_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", local_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _run_git(cmd: List[str], command_desc: str, timeout: int = 300) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise GitSyncError(
            f"{command_desc} 失败: {exc.stderr.strip()}",
            " ".join(cmd),
            exc.stderr,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitSyncError(
            f"{command_desc} 超时", " ".join(cmd), ""
        ) from exc


def preview_remote_branches(remote_url: str, limit: int = 50) -> dict:
    """Return branch list and default branch for a remote repository.

    Used by ``GET /api/repos/branches/preview``.
    """
    result = subprocess.run(
        ["git", "ls-remote", "--heads", remote_url],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    branches = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        ref = line.split()[1]
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])

    default_branch = _detect_default_branch(remote_url)
    return {
        "branches": branches[:limit],
        "default_branch": default_branch,
    }


def _detect_default_branch(remote_url: str) -> str:
    """Detect remote default branch (HEAD ref), fallback to main/master."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", remote_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        for line in result.stdout.splitlines():
            if line.startswith("ref:"):
                ref = line.split()[1]
                if ref.startswith("refs/heads/"):
                    return ref[len("refs/heads/"):]
    except subprocess.CalledProcessError:
        logger.warning("Failed to detect default branch via symref for %s", remote_url)

    # Fallback: try to fetch branch list and pick main/master
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote_url, "main", "master"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        refs = {line.split()[1] for line in result.stdout.strip().splitlines() if line.strip()}
        if "refs/heads/main" in refs:
            return "main"
        if "refs/heads/master" in refs:
            return "master"
    except subprocess.CalledProcessError:
        pass

    return "main"


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

# Repo-level sync lock via Redis SET NX (cross-process), key=sync:lock:{repo_id}.
# The lock TTL (5 min) protects against stale locks left by crashed workers;
# the in-process asyncio lock above is the first layer of dedupe.
_SYNC_LOCK_TTL_SECONDS = 300
_SYNC_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    """Get the shared Redis client (thread-safe connection pool)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _sync_lock_key(repo_id: str) -> str:
    return f"sync:lock:{repo_id}"


def _acquire_sync_lock(repo_id: str) -> Optional[str]:
    """Try to acquire the repo-level sync lock via Redis SET NX.

    Returns a unique token on success, or ``None`` if another sync holds the
    lock. If Redis is unreachable we fail open (log a warning and allow the
    sync) so that a Redis outage never permanently blocks all syncing; the
    in-process asyncio lock still dedupes within this backend instance.
    """
    try:
        token = uuid.uuid4().hex
        ok = _get_redis().set(_sync_lock_key(repo_id), token, nx=True, ex=_SYNC_LOCK_TTL_SECONDS)
        return token if ok else None
    except Exception as exc:
        logger.warning("Redis sync lock unavailable, proceeding without cross-process lock: %s", exc)
        return uuid.uuid4().hex


def _release_sync_lock(repo_id: str, token: Optional[str]) -> None:
    """Release the lock only if we still own it (compare-and-delete)."""
    if not token:
        return
    try:
        _get_redis().eval(_SYNC_LOCK_SCRIPT, 1, _sync_lock_key(repo_id), token)
    except Exception as exc:
        logger.warning("Failed to release Redis sync lock for %s: %s", repo_id, exc)


def _get_sync_lock(repo_id: str) -> asyncio.Lock:
    """Get or create an in-process asyncio lock for a repository."""
    if repo_id not in _sync_locks:
        _sync_locks[repo_id] = asyncio.Lock()
    return _sync_locks[repo_id]


def _log_sync(db, repo_id, message: str, stage: str = "sync") -> None:
    """Write a sync-related message into indexing_logs so the UI can show it."""
    from models import IndexingLog

    try:
        db.add(IndexingLog(repo_id=repo_id, level="info", stage=stage, message=message))
        db.commit()
    except Exception as exc:
        logger.warning("Failed to write sync log for %s: %s", repo_id, exc)
        try:
            db.rollback()
        except Exception:
            pass


def _cleanup_branch_index(db, repo, branch: str) -> None:
    """Delete all indexed data and the local clone for a business branch.

    Called when a business branch is removed from ``active_branches`` so its
    diff index does not linger in the database and its checkout no longer
    occupies disk space. Each table is deleted explicitly (by the branch
    column where available) because cascade relationships may not cover every
    child table.
    """
    from models import (
        CallGraphEdge,
        CodeFile,
        Embedding,
        EmbeddingEnrichment,
        FrameworkRoute,
        SparseEmbedding,
        Symbol,
        SymbolFlowLabel,
    )

    emb_ids = (
        db.query(Embedding.id)
        .filter(Embedding.repo_id == repo.id, Embedding.branch == branch)
        .subquery()
    )
    sym_ids = (
        db.query(Symbol.id)
        .filter(Symbol.repo_id == repo.id, Symbol.branch == branch)
        .subquery()
    )

    db.query(SparseEmbedding).filter(SparseEmbedding.embedding_id.in_(emb_ids)).delete(
        synchronize_session=False
    )
    db.query(EmbeddingEnrichment).filter(
        EmbeddingEnrichment.embedding_id.in_(emb_ids)
    ).delete(synchronize_session=False)
    db.query(SymbolFlowLabel).filter(SymbolFlowLabel.symbol_id.in_(sym_ids)).delete(
        synchronize_session=False
    )
    db.query(CallGraphEdge).filter(
        CallGraphEdge.repo_id == repo.id, CallGraphEdge.branch == branch
    ).delete(synchronize_session=False)
    db.query(FrameworkRoute).filter(
        FrameworkRoute.repo_id == repo.id, FrameworkRoute.branch == branch
    ).delete(synchronize_session=False)
    db.query(Embedding).filter(
        Embedding.repo_id == repo.id, Embedding.branch == branch
    ).delete(synchronize_session=False)
    db.query(Symbol).filter(
        Symbol.repo_id == repo.id, Symbol.branch == branch
    ).delete(synchronize_session=False)
    db.query(CodeFile).filter(
        CodeFile.repo_id == repo.id, CodeFile.branch == branch
    ).delete(synchronize_session=False)

    # Drop the branch from per-branch bookkeeping fields.
    for field, default in (("branch_deleted_files", "{}"), ("branch_commits", "{}")):
        value = json.loads(getattr(repo, field) or default)
        if branch in value:
            del value[branch]
        setattr(repo, field, json.dumps(value))

    db.commit()
    _log_sync(db, repo.id, f"删除业务分支 {branch} 的索引数据（含本地代码副本）", stage="branch")
    logger.info("Cleaned up index data for deactivated branch %s of repo %s", branch, repo.id)

    # Remove the local shallow clone for the branch (guarded against path
    # traversal: only paths strictly inside REPOS_DIR are ever removed).
    local_path = Path(get_repo_local_path(repo, branch))
    repos_root = Path(settings.repos_dir).resolve()
    try:
        resolved = local_path.resolve()
        if resolved != repos_root and repos_root in resolved.parents:
            shutil.rmtree(resolved, ignore_errors=True)
            logger.info("Removed local clone %s for deactivated branch %s", resolved, branch)
    except Exception as exc:
        logger.warning("Failed to remove local clone for branch %s: %s", branch, exc)


async def _sync_repo_branches(repo_id: UUID) -> dict:
    """Orchestrate syncing default branch and active business branches.

    - Acquires a repo-level advisory lock to dedupe concurrent syncs.
    - Syncs ``default_branch`` first.
    - Then diffs each active business branch whenever its HEAD changed or the
      default branch baseline moved forward.
    - Updates ``branch_commits`` and notifies via WebSocket.
    """
    from database import SessionLocal
    from models import Repository
    from services.notifier import notifier
    from services.indexer import index_repo

    repo_id_str = str(repo_id)
    process_lock = _get_sync_lock(repo_id_str)
    if process_lock.locked():
        logger.info("Repo %s sync already in progress (in-process), skip", repo_id)
        return {"status": "skipped", "repo_id": repo_id_str}

    async with process_lock:
        logger.info("[SYNC TRACE] acquired process lock for %s", repo_id)
        db = SessionLocal()
        lock_token = None
        try:
            lock_token = _acquire_sync_lock(repo_id_str)
            if lock_token is None:
                logger.info("Repo %s sync already in progress, skip", repo_id)
                return {"status": "skipped", "repo_id": repo_id_str}

            logger.info("[SYNC TRACE] acquired sync lock for %s", repo_id)
            repo = db.query(Repository).filter(Repository.id == repo_id).first()
            if not repo:
                return {"status": "error", "repo_id": repo_id_str, "message": "repo not found"}

            # 存量仓库简介回填：description 为空时尝试从远程 API 拉取（失败降级为空）。
            if not repo.description and repo.git_url:
                try:
                    from api.repos import _fetch_repo_description
                    repo.description = _fetch_repo_description(repo.git_url) or None
                    db.commit()
                except Exception as exc:
                    logger.warning("Failed to backfill description for %s: %s", repo_id, exc)
                    db.rollback()

            active_branches = json.loads(repo.active_branches or "[]") or [repo.default_branch]
            branch_commits = json.loads(repo.branch_commits or "{}")
            updated_branches: List[dict] = []
            default_branch = repo.default_branch
            _log_sync(db, repo_id, "开始增量同步，检查远程仓库是否有更新", stage="sync")

            # 1. Sync default branch (main/master)
            main_path = get_repo_local_path(repo, default_branch)
            logger.info("[SYNC TRACE] fetching default branch %s", default_branch)
            # fetch_branch 是同步 subprocess 调用，在线程中执行避免阻塞事件循环
            #（启动自动恢复同步时尤为重要，否则 uvicorn 无法响应请求）。
            await asyncio.to_thread(fetch_branch, repo.git_url, main_path, default_branch, default_branch)
            main_commit = await asyncio.to_thread(_get_current_commit, main_path)
            logger.info("[SYNC TRACE] default branch commit %s changed=%s", main_commit, branch_commits.get(default_branch) != main_commit)
            main_changed = branch_commits.get(default_branch) != main_commit

            if main_changed:
                from_commit = branch_commits.get(default_branch)
                _log_sync(db, repo_id, f"检测到 {default_branch} 分支有更新，开始增量索引", stage="sync")
                logger.info("[SYNC TRACE] indexing default branch %s", default_branch)
                await index_repo(repo_id, branch=default_branch)
                branch_commits[default_branch] = main_commit
                repo.branch_commits = json.dumps(branch_commits)
                db.commit()
                updated_branches.append({
                    "branch": default_branch,
                    "from": from_commit,
                    "to": main_commit,
                })

            # 2. Sync business branches (diff indexing)
            for branch in active_branches:
                if branch == default_branch:
                    continue
                local_path = get_repo_local_path(repo, branch)
                await asyncio.to_thread(fetch_branch, repo.git_url, local_path, branch, default_branch)
                current_commit = await asyncio.to_thread(_get_current_commit, local_path)
                if branch_commits.get(branch) != current_commit or main_changed:
                    from_commit = branch_commits.get(branch)
                    _log_sync(db, repo_id, f"业务分支 {branch} 有更新，开始 diff 增量索引", stage="sync")
                    await index_repo(repo_id, branch=branch)
                    branch_commits[branch] = current_commit
                    repo.branch_commits = json.dumps(branch_commits)
                    db.commit()
                    updated_branches.append({
                        "branch": branch,
                        "from": from_commit,
                        "to": current_commit,
                    })

            repo.status = RepoStatus.indexed.value
            repo.error_message = None
            repo.last_indexed_at = datetime.utcnow()
            db.commit()

            if updated_branches:
                _log_sync(
                    db, repo_id,
                    f"增量同步完成，更新分支：{', '.join(u['branch'] for u in updated_branches)}",
                    stage="sync",
                )
            else:
                _log_sync(db, repo_id, "无分支变更，跳过增量同步", stage="sync")

            result = {
                "status": "done",
                "repo_id": repo_id_str,
                "updated_branches": updated_branches,
            }
            logger.info("[SYNC TRACE] sending synced notification for %s", repo_id)
            await notifier.send_repo_update(
                str(repo_id),
                status="synced",
                progress=100.0,
                sync_result=result,
            )
            logger.info("[SYNC TRACE] completed sync for %s", repo_id)
            return result
        except Exception as exc:
            logger.exception("Failed to sync repo %s: %s", repo_id, exc)
            await notifier.send_repo_update(
                str(repo_id),
                status="error",
                progress=0.0,
                error=str(exc),
            )
            raise
        finally:
            _release_sync_lock(repo_id_str, lock_token)
            db.close()
            logger.info("[SYNC TRACE] released locks for %s", repo_id)
