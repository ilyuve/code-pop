"""CodePop FastAPI application entry point."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure the backend directory is first in the path so that our local `mcp`
# package is found before the installed `mcp` SDK package.
_backend_dir = str(Path(__file__).parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from api import repos, search, webhook, ws
from api.admin import llm as admin_llm
from config import settings
from mcp_server.server import get_mcp_app, get_mcp_sse_app, get_mcp_session_manager
from database import SessionLocal, get_db
from exceptions import CodePopException
from models import RepoStatus, Repository
from scripts.db.ensure_database import ensure_database
from services.indexer import index_repo, shutdown_indexer

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


class _TimezoneAwareJSONResponse(JSONResponse):
    """Render naive UTC datetimes with explicit +00:00 offset.

    The backend stores all timestamps as UTC (naive datetimes). Without an
    offset, JavaScript's `new Date(isoString)` treats the value as local time.
    Appending '+00:00' lets the browser convert it to the user's local timezone
    automatically when using `toLocaleString()` / `toLocaleTimeString()`.
    """

    def render(self, content) -> bytes:
        def _encode(obj):
            if isinstance(obj, datetime):
                # Naive datetime is assumed to be UTC; timezone-aware is kept as-is.
                dt = obj.replace(tzinfo=timezone.utc) if obj.tzinfo is None else obj
                return dt.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        encoded = jsonable_encoder(content, custom_encoder={datetime: _encode})
        return json.dumps(encoded, ensure_ascii=False, default=_encode).encode("utf-8")


def _init_db_sync() -> None:
    """Synchronous database initialization wrapper."""
    ensure_database()


async def _recover_indexing_repos() -> None:
    """Recover repos that were in indexing state when the server restarts.

    A server restart means any previous indexing process is gone, so we
    unconditionally reset indexing repos to pending.  The heartbeat column is
    cleared so stale timestamps from the previous run do not confuse future
    checks.  Stale heartbeats are not treated as errors here because the user
    can simply re-trigger indexing once the server is back.
    """
    db = SessionLocal()
    try:
        indexing_repos = db.query(Repository).filter(
            Repository.status == RepoStatus.indexing.value
        ).all()
        if indexing_repos:
            logger.info(
                "Found %d repos stuck in indexing state after restart, resetting to pending...",
                len(indexing_repos),
            )
            for repo in indexing_repos:
                repo.status = RepoStatus.pending.value
                repo.error_message = None
                repo.indexing_heartbeat_at = None
            db.commit()
        else:
            logger.info("No repos to recover from indexing state")
    finally:
        db.close()


async def _migrate_repo_paths() -> None:
    """Migrate legacy repo paths to branch-aware layout at startup."""
    from services.repo_sync import get_repo_local_path, migrate_legacy_repo_path

    db = SessionLocal()
    try:
        repos = db.query(Repository).all()
        for repo in repos:
            migrate_legacy_repo_path(repo)
            expected_path = get_repo_local_path(repo)
            if repo.local_path != expected_path:
                repo.local_path = expected_path
                logger.info("Updated repo %s local_path to %s", repo.id, expected_path)
        if repos:
            db.commit()
    finally:
        db.close()


async def _warmup_models() -> None:
    """Pre-load embedding model at startup to avoid cold-start latency.

    The embedder intentionally has no degradation fallback: if the model cannot
    be loaded, the service must fail fast rather than silently serve
    meaningless pseudo-vectors.
    """
    from services.embedder import Embedder
    embedder = Embedder()
    _ = embedder.encode(["warmup"])
    logger.info("Embedding model warmed up successfully")


_is_test = "pytest" in sys.modules

if not _is_test:
    logger.info("Initializing database...")
    ensure_database()
    logger.info("CodePop backend ready")
else:
    logger.info("Running under pytest; skipping database initialization at import time")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _recover_indexing_repos()
    await _migrate_repo_paths()
    await _warmup_models()

    # 仓库级定时轮询：开启 auto_sync 的仓库定期检查配置分支增量（无需 webhook 回调）
    poll_task = None
    if not _is_test:
        from services.auto_sync import poll_sync_loop

        poll_task = asyncio.create_task(poll_sync_loop())

    mcp_session_manager = get_mcp_session_manager()
    async with mcp_session_manager.run():
        logger.info("MCP session manager started")
        yield
        logger.info("MCP session manager shutting down")

    if poll_task is not None:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="CodePop",
    description="AI Agent oriented code retrieval infrastructure",
    version=settings.api_version,
    lifespan=lifespan,
    default_response_class=_TimezoneAwareJSONResponse,
)


@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down indexer executor...")
    shutdown_indexer()


@app.exception_handler(CodePopException)
async def codepop_exception_handler(request: Request, exc: CodePopException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repos.router)
app.include_router(search.router)
app.include_router(webhook.router)
app.include_router(ws.router)
app.include_router(admin_llm.router)

mcp_app = get_mcp_app()
mcp_sse_app = get_mcp_sse_app()


class _MCPCompatApp:
    """兼容 MCP 客户端对 URL 后缀的协议选择差异。

    部分客户端（如 Trae）会按 URL 路径是否以 ``/sse`` 结尾来自动选择
    传输协议：以 ``/sse`` 结尾走旧版 SSE（SSEClientTransport），否则走
    Streamable HTTP。因此：

    - ``/mcp/sse`` 与 ``/mcp/http`` 均路由到 Streamable HTTP（官方推荐）。
      ``/mcp/http`` 是不以 ``/sse`` 结尾的别名，供按后缀判协议的客户端
      使用，避免其误选旧版 SSE 后因收不到 ``event: endpoint`` 握手而转圈。
    - ``/mcp/sse-legacy`` + ``/mcp/sse-messages`` 提供旧版 SSE transport 备用。

    Streamable HTTP 同样用 GET 建立通知流，因此不能按请求方法把 GET
    分流给旧版 SSE（会破坏 Streamable 握手）。
    """

    def __init__(self, streamable, sse):
        self.streamable = streamable
        self.sse = sse

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            # 备用旧 SSE transport：/mcp/sse-legacy（GET 握手）+ /mcp/sse-messages
            if path in ("/mcp/sse-legacy", "/mcp/sse-legacy/"):
                scope = dict(scope)
                scope["path"] = "/mcp/sse"
                scope["raw_path"] = b"/mcp/sse"
                await self.sse(scope, receive, send)
                return
            if path in ("/mcp/sse-messages", "/mcp/sse-messages/"):
                scope = dict(scope)
                scope["path"] = "/mcp/messages/"
                scope["raw_path"] = b"/mcp/messages/"
                await self.sse(scope, receive, send)
                return
            # Streamable HTTP：无尾斜杠兼容（消除 307）。/mcp/http 是不以
            # /sse 结尾的别名，避免 Trae 等客户端按 URL 后缀误选旧版 SSE。
            if path in ("/mcp/sse", "/mcp/http"):
                scope = dict(scope)
                scope["path"] = "/mcp/sse/"
                scope["raw_path"] = b"/mcp/sse/"
        await self.streamable(scope, receive, send)


app.mount("/mcp", _MCPCompatApp(mcp_app, mcp_sse_app))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": settings.api_version}


@app.get("/health/deep")
def health_deep(db: Session = Depends(get_db)) -> dict:
    """Deep health check including database, pgvector, and embedding model."""
    checks = {
        "api": {"status": "ok"},
        "database": {"status": "unknown"},
        "pgvector": {"status": "unknown"},
        "embedding_model": {"status": "unknown"},
    }

    try:
        db.execute(text("SELECT 1"))
        checks["database"]["status"] = "ok"
    except Exception as e:
        checks["database"]["status"] = "error"
        checks["database"]["error"] = str(e)

    try:
        result = db.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        has_vector = result.scalar()
        if has_vector:
            checks["pgvector"]["status"] = "ok"
        else:
            checks["pgvector"]["status"] = "error"
            checks["pgvector"]["error"] = "pgvector extension not installed"
    except Exception as e:
        checks["pgvector"]["status"] = "error"
        checks["pgvector"]["error"] = str(e)

    try:
        from services.embedder import Embedder
        embedder = Embedder()
        _ = embedder.encode(["health-check"])
        checks["embedding_model"]["status"] = "ok"
        checks["embedding_model"]["model_name"] = settings.embedding_model
        checks["embedding_model"]["dim"] = settings.embedding_dim
    except Exception as e:
        checks["embedding_model"]["status"] = "error"
        checks["embedding_model"]["error"] = str(e)

    all_ok = all(c["status"] == "ok" for c in checks.values())

    return {
        "status": "ok" if all_ok else "error",
        "version": settings.api_version,
        "checks": checks,
    }


@app.get("/test-db")
def test_db():
    try:
        db = SessionLocal()
        repos = db.query(Repository).all()
        return {"count": len(repos), "connected": True}
    except Exception as e:
        return {"error": str(e), "connected": False}
