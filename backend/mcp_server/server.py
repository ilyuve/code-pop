"""MCP Server exposing CodePop tools via streamable HTTP transport with degradation fallback."""

import json
import logging
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from database import get_db_with_retry
from models import CodeFile, Repository, SearchHistory, Symbol
from schemas import SearchResultItem
from services.embedder import Embedder
from services.degradation_tracker import get_degradation_tracker
from services.searcher import Searcher

logger = logging.getLogger(__name__)

mcp = FastMCP("codepop", streamable_http_path="/sse")
embedder = Embedder()


@contextmanager
def _db_session():
    db = get_db_with_retry()
    try:
        yield db
    finally:
        db.close()


def _estimate_output_tokens(results: List[SearchResultItem]) -> int:
    total_chars = sum(len(r.content) for r in results)
    return max(0, total_chars // 4)


def _record_mcp_search(db, query: str, repo_id: Optional[UUID], mode: str, results_count: int, latency_ms: int, output_tokens: int):
    input_tokens = embedder.count_tokens(query)
    history = SearchHistory(
        query=query,
        repo_id=repo_id,
        mode=mode,
        results_count=results_count,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(history)
    db.commit()


@mcp.tool()
def search_code(
    query: str,
    repo_id: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    搜索代码库中的函数、类、实现逻辑或代码位置。

    当用户询问以下任何问题时，请立即调用此工具：
    - "xxx 在哪" / "where is xxx"
    - "xxx 怎么实现的" / "how does xxx work"
    - "搜一下 xxx" / "find xxx"
    - "登录流程" / "authentication flow"
    - "改了 xxx 会影响哪里" / "impact of changing xxx"
    - "为什么报错" / "why does it fail"
    - 任何关于代码位置、实现逻辑、调用关系的自然语言问题

    支持中文和英文自然语言查询。直接传入用户的原话，不需要翻译。
    返回结构化结果：入口点、调用链上下游、涉及文件、代码片段。

    Args:
        query: Natural language query in Chinese or English.
            Examples: '登录流程在哪', 'how does authentication work', '改了 UserService 会影响哪里'
        repo_id: Optional repository UUID to restrict search
        limit: Maximum number of code snippets (default: 10)
    """
    try:
        with _db_session() as db:
            repo_uuid = UUID(repo_id) if repo_id else None
            searcher = Searcher(db)

            start = time.time()
            context = searcher.search_with_context(query, repo_uuid, limit)
            latency_ms = int((time.time() - start) * 1000)
            context.search_latency_ms = latency_ms

            output_tokens = 0
            if context.code_snippets:
                output_tokens = _estimate_output_tokens(context.code_snippets)

            _record_mcp_search(db, query, repo_uuid, "mcp_search", len(context.code_snippets), latency_ms, output_tokens)

            return json.dumps(context.model_dump(), ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("MCP search_code failed: %s\n%s", e, traceback.format_exc())
        get_degradation_tracker().record(
            component="mcp_search_code",
            error_type=type(e).__name__,
            error_message=str(e),
            fallback_action="Returning error response",
        )
        return json.dumps({"error": "服务暂时不可用", "degraded": True}, ensure_ascii=False)


@mcp.tool()
def analyze_impact(
    query: str,
    repo_id: Optional[str] = None,
    depth: int = 3,
) -> str:
    """
    Analyze impact of modifying a symbol: who depends on it, what files are affected.

    Use this when the user asks about changing, refactoring, or deleting a function/class.
    当用户说"改了 xxx"、"删掉 xxx 会怎样"、"重构 xxx"时调用。

    Args:
        query: Symbol name or description.
            Examples: 'UserService.findById', '如果改了登录接口'
        repo_id: Optional repository UUID
        depth: Call chain depth for impact analysis (default: 3)
    """
    try:
        with _db_session() as db:
            repo_uuid = UUID(repo_id) if repo_id else None
            searcher = Searcher(db)

            intent = searcher.intent_analyzer.analyze(query)
            intent.intent_type = "impact_analysis"
            intent.search_strategy = searcher.intent_analyzer._build_strategy("impact_analysis", intent.is_chinese)
            intent.search_strategy.call_depth = depth

            start = time.time()
            context = searcher.search_with_context(query, repo_uuid, 20, intent=intent)
            latency_ms = int((time.time() - start) * 1000)
            context.search_latency_ms = latency_ms
            context.query_intent = "impact_analysis"

            output_tokens = 0
            if context.code_snippets:
                output_tokens = _estimate_output_tokens(context.code_snippets)

            _record_mcp_search(db, query, repo_uuid, "mcp_impact", len(context.code_snippets), latency_ms, output_tokens)

            return json.dumps(context.model_dump(), ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("MCP analyze_impact failed: %s\n%s", e, traceback.format_exc())
        get_degradation_tracker().record(
            component="mcp_analyze_impact",
            error_type=type(e).__name__,
            error_message=str(e),
            fallback_action="Returning error response",
        )
        return json.dumps({"error": "服务暂时不可用", "degraded": True}, ensure_ascii=False)


@mcp.tool()
def list_repositories() -> str:
    """List all indexed code repositories."""
    try:
        with _db_session() as db:
            repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
            result = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "git_url": r.git_url,
                    "status": r.status,
                    "last_indexed_at": r.last_indexed_at.isoformat() if r.last_indexed_at else None,
                }
                for r in repos
            ]
            return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("MCP list_repositories failed: %s\n%s", e, traceback.format_exc())
        get_degradation_tracker().record(
            component="mcp_list_repositories",
            error_type=type(e).__name__,
            error_message=str(e),
            fallback_action="Returning error response",
        )
        return json.dumps({"error": "服务暂时不可用", "degraded": True}, ensure_ascii=False)


@mcp.tool()
def list_file_symbols(repo_id: str, file_path: str) -> str:
    """
    List symbols (functions, classes, methods) for a given file.

    Args:
        repo_id: Repository UUID
        file_path: Relative file path
    """
    try:
        with _db_session() as db:
            code_file = (
                db.query(CodeFile)
                .filter(CodeFile.repo_id == UUID(repo_id), CodeFile.path == file_path)
                .first()
            )
            if not code_file:
                return json.dumps([], ensure_ascii=False)
            symbols = (
                db.query(Symbol)
                .filter(Symbol.file_id == code_file.id)
                .order_by(Symbol.line)
                .all()
            )
            result = [
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
            return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("MCP list_file_symbols failed: %s\n%s", e, traceback.format_exc())
        get_degradation_tracker().record(
            component="mcp_list_file_symbols",
            error_type=type(e).__name__,
            error_message=str(e),
            fallback_action="Returning error response",
        )
        return json.dumps({"error": "服务暂时不可用", "degraded": True}, ensure_ascii=False)


@mcp.tool()
def codepop_impact(
    symbol_name: str,
    repo_id: str = None,
) -> str:
    """
    分析修改某个函数的影响面。

    Args:
        symbol_name: 要分析的函数/方法名
        repo_id: 仓库 ID，默认使用配置中的默认仓库

    Returns:
        影响面分析报告，包括受影响的路由和调用链
    """
    try:
        with _db_session() as db:
            from services.impact_analyzer import ImpactAnalyzer

            target_repo = UUID(repo_id) if repo_id else None
            analyzer = ImpactAnalyzer(db)
            result = analyzer.analyze(symbol_name, target_repo)

            lines = [
                f"Impact Analysis: `{result.symbol}`",
                f"Location: {result.file_path}:{result.line}",
                f"Call depth: {result.depth}",
                f"Risk level: {result.risk_level.upper()}",
                "",
            ]

            if result.affected_routes:
                lines.append("Affected HTTP routes:")
                for route in result.affected_routes:
                    lines.append(
                        f"  {route['method']} {route['path']} "
                        f"({route['framework']}) → {route['handler']}"
                    )
            else:
                lines.append("No HTTP routes directly affected.")

            if result.upstream_chain:
                lines.extend(["", "Upstream call chain:"])
                lines.append(" → ".join(result.upstream_chain))

            return "\n".join(lines)
    except Exception as e:
        logger.error("MCP codepop_impact failed: %s\n%s", e, traceback.format_exc())
        get_degradation_tracker().record(
            component="mcp_codepop_impact",
            error_type=type(e).__name__,
            error_message=str(e),
            fallback_action="Returning error response",
        )
        return json.dumps({"error": "服务暂时不可用", "degraded": True}, ensure_ascii=False)


def get_mcp_app():
    """Get the streamable HTTP ASGI app for mounting in FastAPI."""
    return mcp.streamable_http_app()


def get_mcp_session_manager():
    """Get the MCP session manager for lifespan management."""
    # 触发 session manager 的创建
    _ = mcp.streamable_http_app()
    return mcp._session_manager
