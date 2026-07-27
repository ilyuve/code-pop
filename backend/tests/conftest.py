"""Shared pytest configuration and dependency mocks for backend tests."""

import sys
from unittest.mock import MagicMock

# Avoid pulling heavy ML dependencies into unit tests.
_sentence_transformers = MagicMock()
_sentence_transformers.SentenceTransformer = MagicMock
_sentence_transformers.CrossEncoder = MagicMock
sys.modules["sentence_transformers"] = _sentence_transformers

_flag_embedding = MagicMock()
_flag_embedding.BGEM3FlagModel = MagicMock
sys.modules["FlagEmbedding"] = _flag_embedding

_tree_sitter = MagicMock()
sys.modules["tree_sitter"] = _tree_sitter

# Register parser language modules as empty mocks so indexer/parser imports work.
for _lang in (
    "tree_sitter_python",
    "tree_sitter_typescript",
    "tree_sitter_javascript",
    "tree_sitter_go",
    "tree_sitter_java",
    "tree_sitter_rust",
    "tree_sitter_cpp",
):
    sys.modules[_lang] = MagicMock()

# Mock MCP server SDK to avoid heavy dependencies in unit tests.
_mcp_server = MagicMock()
_mcp_server.FastMCP = MagicMock
_mcp_server.Server = MagicMock


def _tool_decorator(*args, **kwargs):
    def wrapper(fn):
        return fn
    return wrapper


_mcp_server.tool = _tool_decorator
_mcp_server.FastMCP.tool = _tool_decorator
_mcp_server.FastMCP.streamable_http_app = MagicMock(return_value=MagicMock())
_mcp_server.FastMCP.run = MagicMock()
sys.modules["mcp"] = _mcp_server
sys.modules["mcp.server"] = _mcp_server
sys.modules["mcp.server.fastmcp"] = _mcp_server
sys.modules["mcp.server.session"] = _mcp_server
sys.modules["mcp.server.stdio"] = _mcp_server
sys.modules["mcp.types"] = _mcp_server
