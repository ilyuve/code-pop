"""Python code parser using the stdlib `ast` module.

Replaces tree-sitter for Python files to avoid C-level SIGBUS crashes on
certain syntax (list comprehension + dict literal in tree-sitter 0.24).
Pure-Python ast.parse correctly handles Unicode (including Chinese strings
and comments) and never crashes the interpreter.

The extracted symbols and calls are equivalent to what tree-sitter produced:
- FunctionDef / AsyncFunctionDef -> type="function", kind="function"
- ClassDef                       -> type="class",     kind="class"
- top-level defs are is_exported=True; methods carry parent_name=<class name>
- ast.Call nodes -> (caller_function_name, callee_name) pairs
"""

from __future__ import annotations

import ast
import hashlib
import logging
from typing import List, Optional, Tuple

from services.parser import (
    ParseResult,
    Symbol,
    _chunk_by_lines,
    _chunk_by_symbols,
)

logger = logging.getLogger(__name__)


def _function_name(call_func: ast.AST) -> Optional[str]:
    """Extract a callee name from an ast.Call.func node.

    - ast.Name(id=...)            -> id
    - ast.Attribute(attr=...)     -> attr (the method name, e.g. foo.bar -> bar)
    - ast.Subscript / ast.Call    -> None (too complex to be a useful callee)
    """
    if isinstance(call_func, ast.Name):
        return call_func.id
    if isinstance(call_func, ast.Attribute):
        return call_func.attr
    return None


class _SymbolExtractor(ast.NodeVisitor):
    """Walk the AST and collect Symbol entries with parent_name tracking."""

    def __init__(self) -> None:
        self.symbols: List[Symbol] = []
        self._stack: List[Tuple[str, str]] = []  # (name, type) of enclosing scopes

    def _push(self, name: str, sym_type: str) -> None:
        self._stack.append((name, sym_type))

    def _pop(self) -> None:
        if self._stack:
            self._stack.pop()

    def _enclosing_parent(self) -> Optional[str]:
        # The immediate function/class scope, if any.
        return self._stack[-1][0] if self._stack else None

    def _is_top_level(self) -> bool:
        # is_exported mirrors tree-sitter behavior: defs directly under module
        # or under a class body (methods) count as exported.
        return len(self._stack) <= 1

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent = self._enclosing_parent()
        is_method = bool(parent and self._stack[-1][1] == "class")
        self.symbols.append(
            Symbol(
                name=node.name,
                type="method" if is_method else "function",
                kind="method" if is_method else "function",
                line=node.lineno,
                column=node.col_offset,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                end_column=getattr(node, "end_col_offset", node.col_offset) or node.col_offset,
                is_exported=self._is_top_level(),
                parent_name=parent,
            )
        )
        self._push(node.name, "function")
        self.generic_visit(node)
        self._pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        parent = self._enclosing_parent()
        self.symbols.append(
            Symbol(
                name=node.name,
                type="class",
                kind="class",
                line=node.lineno,
                column=node.col_offset,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                end_column=getattr(node, "end_col_offset", node.col_offset) or node.col_offset,
                is_exported=self._is_top_level(),
                parent_name=parent,
            )
        )
        self._push(node.name, "class")
        self.generic_visit(node)
        self._pop()


class _CallExtractor(ast.NodeVisitor):
    """Walk the AST and collect (caller, callee) pairs.

    caller is the name of the immediately enclosing FunctionDef/AsyncFunctionDef
    (methods use the function name; module-level calls are skipped since they
    have no caller symbol).
    """

    def __init__(self, symbols: List[Symbol]) -> None:
        self.symbols = symbols
        self.calls: List[Tuple[str, str]] = []
        # Sorted (start_line, end_line, name) of function-like symbols.
        self._func_ranges: List[Tuple[int, int, str]] = sorted(
            ((s.line, s.end_line, s.name) for s in symbols if s.type in ("function", "method")),
            key=lambda x: (x[0], x[1]),
        )
        self._caller_stack: List[str] = []

    def _caller_for(self, node: ast.AST) -> Optional[str]:
        # Prefer the visitor-maintained stack (accurate for nested scopes).
        if self._caller_stack:
            return self._caller_stack[-1]
        # Fall back to range lookup for module-level calls.
        line = getattr(node, "lineno", 0)
        for start, end, name in self._func_ranges:
            if start <= line <= end:
                return name
        return None

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._caller_stack.append(node.name)
        self.generic_visit(node)
        self._caller_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        callee = _function_name(node.func)
        if callee:
            caller = self._caller_for(node)
            if caller and caller != callee:
                self.calls.append((caller, callee))
        self.generic_visit(node)


def _extract_symbols(tree: ast.Module) -> List[Symbol]:
    extractor = _SymbolExtractor()
    extractor.visit(tree)
    return extractor.symbols


def _extract_calls(tree: ast.Module, symbols: List[Symbol]) -> List[Tuple[str, str]]:
    extractor = _CallExtractor(symbols)
    extractor.visit(tree)
    return extractor.calls


def parse_python(
    file_path: str, content: str, max_chunk_lines: int = 200
) -> Optional[ParseResult]:
    """Parse Python source with the stdlib ast module.

    Returns a ParseResult with symbols, chunks and calls. On SyntaxError the
    file is still chunked by lines (so it remains searchable) but symbols and
    calls are empty -- this is the only acceptable degradation, since the file
    itself has a syntax error.
    """
    size_bytes = len(content.encode("utf-8"))
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    lines = content.split("\n")

    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError as exc:
        logger.warning(
            "Python syntax error in %s:%s:%s: %s -- falling back to line chunks",
            file_path,
            exc.lineno,
            exc.offset,
            exc.msg,
        )
        chunks = _chunk_by_lines(lines, max_chunk_lines)
        return ParseResult(
            file_path=file_path,
            language="python",
            symbols=[],
            chunks=chunks,
            size_bytes=size_bytes,
            content_hash=content_hash,
            calls=[],
        )

    symbols = _extract_symbols(tree)
    calls = _extract_calls(tree, symbols)
    chunks = _chunk_by_symbols(lines, symbols, max_chunk_lines)

    return ParseResult(
        file_path=file_path,
        language="python",
        symbols=symbols,
        chunks=chunks,
        size_bytes=size_bytes,
        content_hash=content_hash,
        calls=calls,
    )
