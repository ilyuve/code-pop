"""Git clone / pull operations for repositories."""

import logging
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from config import settings

logger = logging.getLogger(__name__)


class GitSyncError(Exception):
    """Custom exception for git sync errors with detailed message."""

    def __init__(self, message: str, command: str, stderr: str = ""):
        self.command = command
        self.stderr = stderr
        super().__init__(message)


def _safe_name(name: str) -> str:
    """Sanitize repository name for filesystem path."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()


def _repo_local_path(name: str) -> Path:
    return settings.repos_dir / _safe_name(name)


def clone_or_pull(name: str, git_url: str, local_path: Optional[str] = None) -> Path:
    """Clone a new repository or pull an existing one. If local_path is provided and git_url is empty, use local path directly."""
    if local_path and not git_url:
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            raise GitSyncError(f"本地路径不存在: {local_path}", "local_path_check")
        if not local_path_obj.is_dir():
            raise GitSyncError(f"本地路径不是目录: {local_path}", "local_path_check")
        logger.info("Using local path: %s", local_path)
        return local_path_obj

    target_path = _repo_local_path(name)
    target_path.mkdir(parents=True, exist_ok=True)

    if (target_path / ".git").exists():
        logger.info("Pulling existing repo at %s", target_path)
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(target_path),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            logger.info("Git pull succeeded: %s", result.stdout.strip())
        except subprocess.CalledProcessError as exc:
            if "Couldn't connect to server" in exc.stderr or "Connection refused" in exc.stderr or "Failed to connect" in exc.stderr:
                logger.warning("Git pull failed due to network issue, using local files: %s", exc.stderr.strip())
            else:
                error_msg = f"Git pull 失败: {exc.stderr.strip()}"
                logger.error(error_msg)
                if "Authentication failed" in exc.stderr:
                    error_msg = f"GitHub 认证失败，请检查 Git 凭证配置。错误: {exc.stderr.strip()}"
                elif "not something we can merge" in exc.stderr:
                    error_msg = f"本地分支与远程分支冲突，请先手动处理。错误: {exc.stderr.strip()}"
                raise GitSyncError(error_msg, "git pull --ff-only", exc.stderr)
        except subprocess.TimeoutExpired:
            logger.warning("Git pull timed out, using local files")
    else:
        logger.info("Cloning %s into %s", git_url, target_path)
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(target_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            logger.info("Git clone succeeded")
        except subprocess.CalledProcessError as exc:
            if "Couldn't connect to server" in exc.stderr or "Connection refused" in exc.stderr or "Failed to connect" in exc.stderr:
                raise GitSyncError(f"无法连接到 GitHub，请检查网络连接后重试。错误: {exc.stderr.strip()}", f"git clone {git_url}", exc.stderr)
            error_msg = f"Git clone 失败: {exc.stderr.strip()}"
            logger.error(error_msg)
            if "Authentication failed" in exc.stderr:
                error_msg = f"GitHub 认证失败，请检查 Git 凭证配置。错误: {exc.stderr.strip()}"
            elif "not found" in exc.stderr:
                error_msg = f"仓库地址不存在或无权访问: {git_url}。错误: {exc.stderr.strip()}"
            raise GitSyncError(error_msg, f"git clone {git_url}", exc.stderr)
        except subprocess.TimeoutExpired:
            raise GitSyncError("Git clone timed out, please check network connection", f"git clone {git_url}")

    return target_path


def is_valid_git_url(url: str) -> bool:
    """Basic validation of a Git URL."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", "ssh", "git"):
        return True
    if "@" in url and ":" in url:
        return True
    return False
