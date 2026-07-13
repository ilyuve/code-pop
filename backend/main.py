"""CodePop FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys
from pathlib import Path

# Ensure the backend directory is first in the path so that our local `mcp`
# package is found before the installed `mcp` SDK package.
_backend_dir = str(Path(__file__).parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from api import repos, search, webhook, ws
from config import settings
from mcp_server.server import get_mcp_app, get_mcp_session_manager
from database import SessionLocal
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


logger.info("Initializing database...")
init_db()
logger.info("CodePop backend ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
