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
from exceptions import CodePopException
from mcp_server.server import mcp_sse_endpoint, sse_transport
from scripts.init_db import init_db
from services.indexer import shutdown_indexer

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def _init_db_sync() -> None:
    """Synchronous database initialization wrapper."""
    init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    logger.info("Initializing database...")
    await loop.run_in_executor(None, _init_db_sync)
    logger.info("CodePop backend ready")
    yield
    logger.info("Shutting down indexer executor...")
    shutdown_indexer()


app = FastAPI(
    title="CodePop",
    description="AI Agent oriented code retrieval infrastructure",
    version=settings.api_version,
    lifespan=lifespan,
)


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

# MCP SSE endpoint
app.add_api_route("/mcp/sse", mcp_sse_endpoint, methods=["GET"])
app.add_api_route("/mcp/messages/", sse_transport.handle_post_message, methods=["POST"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": settings.api_version}
