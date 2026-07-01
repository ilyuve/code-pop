"""MCP Server exposing CodePop tools via SSE transport."""

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

from database import SessionLocal
from models import CodeFile, Repository, Symbol
from schemas import SearchResultItem
from services.searcher import Searcher

logger = logging.getLogger(__name__)

# MCP server instance
mcp_server = Server("codepop")

# SSE transport endpoint; message posting path is internal.
sse_transport = SseServerTransport("/mcp/messages/")


@contextmanager
def _db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="codepop_search",
            description="Hybrid code search across indexed repositories using vector, symbol, BM25 and call graph signals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language or keyword query"},
                    "repo_id": {"type": "string", "description": "Optional repository UUID to restrict search"},
                    "limit": {"type": "integer", "default": 10, "description": "Maximum number of results"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="codepop_repos",
            description="List all indexed repositories.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="codepop_symbols",
            description="List symbols for a given file in a repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Repository UUID"},
                    "file_path": {"type": "string", "description": "Relative file path within the repository"},
                },
                "required": ["repo_id", "file_path"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any | None) -> List[TextContent]:
    arguments = arguments or {}
    try:
        if name == "codepop_search":
            results = _tool_codepop_search(arguments)
        elif name == "codepop_repos":
            results = _tool_codepop_repos()
        elif name == "codepop_symbols":
            results = _tool_codepop_symbols(arguments)
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, default=str))]
    except Exception as exc:
        logger.exception("MCP tool %s failed: %s", name, exc)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


def _tool_codepop_search(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = arguments["query"]
    repo_id = arguments.get("repo_id")
    limit = int(arguments.get("limit", 10))

    with _db_session() as db:
        repo_uuid = UUID(repo_id) if repo_id else None
        searcher = Searcher(db)
        results: List[SearchResultItem] = searcher.hybrid_search(query, repo_uuid, limit)
        return [r.model_dump() for r in results]


def _tool_codepop_repos() -> List[Dict[str, Any]]:
    with _db_session() as db:
        repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "git_url": r.git_url,
                "status": r.status,
                "last_indexed_at": r.last_indexed_at.isoformat() if r.last_indexed_at else None,
            }
            for r in repos
        ]


def _tool_codepop_symbols(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    repo_id = UUID(arguments["repo_id"])
    file_path = arguments["file_path"]

    with _db_session() as db:
        code_file = (
            db.query(CodeFile)
            .filter(CodeFile.repo_id == repo_id, CodeFile.path == file_path)
            .first()
        )
        if not code_file:
            return []
        symbols = (
            db.query(Symbol)
            .filter(Symbol.file_id == code_file.id)
            .order_by(Symbol.line)
            .all()
        )
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "type": s.type,
                "kind": s.kind,
                "line": s.line,
                "column": s.column,
                "end_line": s.end_line,
                "is_exported": bool(s.is_exported),
            }
            for s in symbols
        ]


async def mcp_sse_endpoint(request: Request):
    """FastAPI-compatible SSE endpoint for the MCP server."""
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )
    return Response()
