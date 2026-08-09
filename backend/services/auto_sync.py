"""仓库级定时轮询自动增量同步。

无需 webhook 回调：后台定期 fetch 配置分支（default + active_branches）并做增量索引，
适用于本地开发 / 内网无法接收平台回调的场景。仓库开启 auto_sync 开关后生效。

日志设计（方便排查同步失败）：
- 服务端日志（docker compose logs backend）记录每次扫描、触发、跳过与任务结果；
- 索引日志面板（仓库详情页）记录每次轮询的触发与完成/失败，失败为 error 级红色展示。
"""

import asyncio
import logging
import time
from typing import Dict, Optional
from uuid import UUID

from database import SessionLocal
from models import Repository
from services.repo_sync import _log_sync

logger = logging.getLogger(__name__)

# 默认轮询间隔（分钟），仓库可在 5 / 15 / 30 / 60 中自行配置
DEFAULT_POLL_INTERVAL_MINUTES = 5
# 调度循环扫描间隔（秒）
SCAN_INTERVAL_SECONDS = 60

# 内存记录上次轮询时间（单进程场景足够，重启后首次扫描会立即触发一次检查）
_last_polled: Dict[UUID, float] = {}


def _format_elapsed(seconds: float) -> str:
    """格式化耗时：小于 1 分钟显示秒，否则显示分钟。"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}min"


def _on_sync_done(repo_id: UUID, repo_name: str, scheduled_at: float, task: asyncio.Task) -> None:
    """同步任务完成回调：记录结果到服务端日志与索引日志面板。

    ``_sync_repo_branches`` 失败时内部会 re-raise，因此这里通过 task.result()
    捕获异常并记录为 error，方便后续排查。
    """
    elapsed = time.monotonic() - scheduled_at
    db = SessionLocal()
    try:
        try:
            result = task.result()
        except asyncio.CancelledError:
            logger.warning(
                "Auto-sync task cancelled for repo %s (name=%s) after %s",
                repo_id, repo_name, _format_elapsed(elapsed),
            )
            return
        except Exception as exc:
            logger.error(
                "Auto-sync FAILED for repo %s (name=%s) after %s: %s",
                repo_id, repo_name, _format_elapsed(elapsed), exc,
                exc_info=True,
            )
            _log_sync(db, repo_id, f"定时自动增量检查失败：{exc}", stage="sync", level="error")
            return

        status = result.get("status", "unknown") if isinstance(result, dict) else result
        if isinstance(result, dict) and status == "error":
            message = result.get("message") or "未知错误"
            logger.error(
                "Auto-sync FAILED for repo %s (name=%s) after %s: %s",
                repo_id, repo_name, _format_elapsed(elapsed), message,
            )
            _log_sync(db, repo_id, f"定时自动增量检查失败：{message}", stage="sync", level="error")
            return

        if isinstance(result, dict) and status == "skipped":
            logger.info(
                "Auto-sync skipped for repo %s (name=%s) after %s: 已有同步在进行中",
                repo_id, repo_name, _format_elapsed(elapsed),
            )
            _log_sync(db, repo_id, "定时自动增量检查：仓库正在同步中，本次跳过", stage="sync")
            return

        updated = result.get("updated_branches", []) if isinstance(result, dict) else []
        if updated:
            branch_desc = ", ".join(str(u.get("branch", "?")) for u in updated)
            message = f"定时自动增量检查完成：更新分支 {branch_desc}（耗时 {_format_elapsed(elapsed)}）"
        else:
            message = f"定时自动增量检查完成：无分支变更（耗时 {_format_elapsed(elapsed)}）"
        logger.info("Auto-sync done for repo %s (name=%s): %s", repo_id, repo_name, message)
        _log_sync(db, repo_id, message, stage="sync")
    finally:
        db.close()


def _schedule_sync(repo: Repository) -> Optional[asyncio.Task]:
    """调度一次仓库同步（来源标记为定时增量），并绑定完成回调记录详细结果。"""
    from services.repo_sync import _sync_repo_branches

    scheduled_at = time.monotonic()
    try:
        task = asyncio.create_task(_sync_repo_branches(repo.id, "auto"))
        task.add_done_callback(
            lambda t, rid=repo.id, rname=repo.name: _on_sync_done(rid, rname, scheduled_at, t)
        )
        return task
    except Exception as exc:
        logger.warning(
            "Failed to schedule auto-sync for repo %s (name=%s): %s",
            repo.id, repo.name, exc,
        )
        return None


async def _run_due_poll_syncs() -> None:
    """扫描开启 auto_sync 的仓库，到点的触发一次增量同步。

    ``_sync_repo_branches`` 内部有 repo 级同步锁去重，与 webhook / 手动同步并发时
    只会执行一次，因此这里可安全地按间隔重复调度。间隔按仓库 auto_sync_interval
    配置（5 / 15 / 30 / 60 分钟）独立计时。
    """
    now = time.monotonic()

    db = SessionLocal()
    try:
        repos = (
            db.query(Repository)
            .filter(
                Repository.auto_sync.is_(True),
                Repository.git_url.isnot(None),
                Repository.git_url != "",
            )
            .all()
        )
    finally:
        db.close()

    logger.info("Auto-sync poll scan: %d repo(s) with auto_sync enabled", len(repos))
    triggered = 0
    for repo in repos:
        interval = (repo.auto_sync_interval or DEFAULT_POLL_INTERVAL_MINUTES) * 60
        last = _last_polled.get(repo.id)
        if last is not None and now - last < interval:
            logger.debug(
                "Auto-sync skip repo %s (name=%s): 距上次轮询 %.0fs，未到 %d 分钟间隔",
                repo.id, repo.name, now - last, interval // 60,
            )
            continue
        since_desc = f"{now - last:.0f}s" if last is not None else "首次"
        _last_polled[repo.id] = now
        triggered += 1
        logger.info(
            "Auto-sync poll trigger repo %s (name=%s, default_branch=%s, interval=%dmin, since_last=%s, url=%s)",
            repo.id, repo.name, repo.default_branch, interval // 60, since_desc, repo.git_url,
        )
        _schedule_sync(repo)
    logger.info(
        "Auto-sync poll scan finished: %d triggered, %d skipped",
        triggered, len(repos) - triggered,
    )


async def poll_sync_loop() -> None:
    """后台常驻循环：每隔 SCAN_INTERVAL_SECONDS 扫描一次到点仓库。"""
    logger.info(
        "Auto-sync poll loop started (default interval %d min per repo, scan %ds)",
        DEFAULT_POLL_INTERVAL_MINUTES,
        SCAN_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _run_due_poll_syncs()
        except Exception:
            logger.exception("Auto-sync poll iteration failed")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
