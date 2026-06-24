"""Git clone / pull operations for repositories."""

import logging
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from config import settings

logger = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    """Sanitize repository name for filesystem path."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()


def _repo_local_path(name: str) -> Path:
    return settings.repos_dir / _safe_name(name)


def clone_or_pull(name: str, git_url: str) -> Path:
    """Clone a new repository or pull an existing one."""
    local_path = _repo_local_path(name)
    local_path.mkdir(parents=True, exist_ok=True)

    if (local_path / ".git").exists():
        logger.info("Pulling existing repo at %s", local_path)
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(local_path),
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        logger.info("Cloning %s into %s", git_url, local_path)
        subprocess.run(
            ["git", "clone", "--depth", "1", git_url, str(local_path)],
            check=True,
            capture_output=True,
            text=True,
        )

    return local_path


def is_valid_git_url(url: str) -> bool:
    """Basic validation of a Git URL."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", "ssh", "git"):
        return True
    if "@" in url and ":" in url:
        return True
    return False
