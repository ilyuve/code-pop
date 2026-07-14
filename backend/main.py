"""CodePop FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from config import settings
from mcp_server.server import get_mcp_app, get_mcp_session_manager
from database import SessionLocal, get_db
from exceptions import CodePopException
from models import RepoStatus, Repository
from scripts.init_db import init_db
from services.indexer import index_repo, shutdown_indexer

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def _init_db_sync() -> None:
    """Synchronous database initialization wrapper."""
    init_db()


async def _recover_indexing_repos() -> None:
    """Recover repos that were in indexing state when server crashed."""
    db = SessionLocal()
    try:
        indexing_repos = db.query(Repository).filter(
            Repository.status == RepoStatus.indexing.value
        ).all()
        if indexing_repos:
            logger.info("Found %d repos in indexing state, resetting to pending...", len(indexing_repos))
            for repo in indexing_repos:
                repo.status = RepoStatus.pending.value
            db.commit()
        else:
            logger.info("No repos to recover from indexing state")
    finally:
        db.close()


async def _warmup_models() -> None:
    """Pre-load embedding model at startup to avoid cold-start latency."""
    try:
        from services.embedder import Embedder
        embedder = Embedder()
        _ = embedder.encode(["warmup"])
        logger.info("Embedding model warmed up successfully")
    except Exception as e:
        logger.error("Failed to warm up embedding model: %s", e)
        logger.error("Search will be unavailable until model is loaded.")


logger.info("Initializing database...")
init_db()
logger.info("CodePop backend ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _recover_indexing_repos()
    await _warmup_models()

    mcp_session_manager = get_mcp_session_manager()
    async with mcp_session_manager.run():
        logger.info("MCP session manager started")
        yield
        logger.info("MCP session manager shutting down")


app = FastAPI(
    title="CodePop",
    description="AI Agent oriented code retrieval infrastructure",
    version=settings.api_version,
    lifespan=lifespan,
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

mcp_app = get_mcp_app()
app.mount("/mcp", mcp_app)


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
        if embedder.model is not None:
            checks["embedding_model"]["status"] = "ok"
            checks["embedding_model"]["model_name"] = settings.embedding_model
            checks["embedding_model"]["dim"] = settings.embedding_dim
        else:
            checks["embedding_model"]["status"] = "degraded"
            checks["embedding_model"]["error"] = "Model not loaded"
    except Exception as e:
        checks["embedding_model"]["status"] = "error"
        checks["embedding_model"]["error"] = str(e)

    all_ok = all(c["status"] in ("ok", "degraded") for c in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "version": settings.api_version,
        "checks": checks,
    }


@app.get("/test-db")
def test_db():
    import os
    db_path = "./codepop.db"
    exists = os.path.exists(db_path)
    size = os.path.getsize(db_path) if exists else 0
    
    try:
        db = SessionLocal()
        repos = db.query(Repository).all()
        return {"count": len(repos), "db_exists": exists, "db_size": size}
    except Exception as e:
        return {"error": str(e), "db_exists": exists, "db_size": size}
