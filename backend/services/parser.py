"""tree-sitter based code parser for multiple languages."""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tree_sitter import Language as TSLanguage, Parser, Tree
from tree_sitter_python import language as python_language

logger = logging.getLogger(__name__)


def _load_language(language: str) -> Optional[TSLanguage]:
    """Lazy load tree-sitter language binding."""
    if language == "python":
        return TSLanguage(python_language())
    if language == "typescript":
        try:
            from tree_sitter_typescript import language_typescript, language_tsx
            return TSLanguage(language_typescript())
        except Exception:
            try:
                from tree_sitter_typescript import language as ts_language
                return TSLanguage(ts_language())
            except Exception:
                return None
    if language == "javascript":
        try:
            from tree_sitter_javascript import language as js_language
            return TSLanguage(js_language())
        except Exception:
            return None
    if language == "go":
        try:
            from tree_sitter_go import language as go_language
            return TSLanguage(go_language())
        except Exception:
            return None
    if language == "java":
        try:
            from tree_sitter_java import language as java_language
            return TSLanguage(java_language())
        except Exception:
            return None
    if language == "rust":
        try:
            from tree_sitter_rust import language as rust_language
            return TSLanguage(rust_language())
        except Exception:
            return None
    if language == "cpp":
        try:
            from tree_sitter_cpp import language as cpp_language
            return TSLanguage(cpp_language())
        except Exception:
            return None
    return None


LANGUAGE_BY_EXTENSION: Dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build",
    ".next", ".nuxt", "target", ".idea", ".vscode", "vendor",
}

SKIP_PATTERNS = (".env", ".lock", ".min.js", ".map", ".DS_Store")

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".rar", ".7z", ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2",
    ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".webm",
}


@dataclass
class Symbol:
    name: str
    type: str
    kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    is_exported: bool = False
    parent_name: Optional[str] = None


@dataclass
class Chunk:
    content: str
    start_line: int
    end_line: int
    symbols: List[Symbol] = field(default_factory=list)


@dataclass
class ParseResult:
    file_path: str
    language: str
    symbols: List[Symbol]
    chunks: List[Chunk]
    size_bytes: int
    content_hash: str
    calls: List[Tuple[str, str]] = field(default_factory=list)  # (caller_name, callee_name)


def detect_language(file_path: str) -> Optional[str]:
    ext = Path(file_path).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(ext)


def should_skip_path(path: str) -> bool:
    parts = Path(path).parts
    if any(p in SKIP_DIRS for p in parts):
        return True
    if path.endswith(SKIP_PATTERNS):
        return True
    if Path(path).suffix.lower() in BINARY_EXTENSIONS:
        return True
    return False


def is_binary(content: bytes) -> bool:
    return b"\x00" in content


def _symbol_type(node_type: str) -> Optional[Tuple[str, str]]:
    mapping = {
        "function_definition": ("function", "function"),
        "function_declaration": ("function", "function"),
        "method_declaration": ("method", "method"),
        "method_definition": ("method", "method"),
        "class_definition": ("class", "class"),
        "class_declaration": ("class", "class"),
        "interface_declaration": ("interface", "interface"),
        "type_alias_declaration": ("type", "type"),
        "enum_declaration": ("enum", "enum"),
        "variable_declaration": ("variable", "variable"),
        "property_declaration": ("property", "property"),
        "struct_item": ("class", "struct"),
        "function_item": ("function", "function"),
        "impl_item": ("class", "impl"),
        "trait_item": ("interface", "trait"),
    }
    return mapping.get(node_type)


def _node_name(node) -> Optional[str]:
    name_field = node.child_by_field_name("name")
    if name_field:
        return name_field.text.decode("utf-8", errors="replace")

    if node.type == "variable_declaration":
        decl = node.child_by_field_name("declarator")
        if decl:
            name_field = decl.child_by_field_name("name")
            if name_field:
                return name_field.text.decode("utf-8", errors="replace")

    return None


def _is_exported(node, language: str) -> bool:
    if language in ("typescript", "javascript"):
        modifiers = node.child_by_field_name("modifiers")
        if modifiers:
            text = modifiers.text.decode("utf-8", errors="replace")
            return "export" in text
    if language == "python":
        # top-level functions/classes are considered exported for search
        return node.parent is not None and node.parent.type in ("module", "block")
    if language == "rust":
        text = node.text.decode("utf-8", errors="replace")
        return text.lstrip().startswith("pub ")
    return False


def _extract_symbols(root_node, language: str) -> List[Symbol]:
    symbols: List[Symbol] = []

    def walk(node, parent_name: Optional[str] = None):
        sym_type = _symbol_type(node.type)
        current_name = None
        if sym_type:
            name = _node_name(node)
            if name:
                current_name = name
                symbols.append(
                    Symbol(
                        name=name,
                        type=sym_type[0],
                        kind=sym_type[1],
                        line=node.start_point.row + 1,
                        column=node.start_point.column,
                        end_line=node.end_point.row + 1,
                        end_column=node.end_point.column,
                        is_exported=_is_exported(node, language),
                        parent_name=parent_name,
                    )
                )
        for child in node.children:
            if child.type == "comment":
                continue
            walk(child, current_name or parent_name)

    walk(root_node)
    return symbols


def _extract_calls(root_node, symbols: List[Symbol]) -> List[Tuple[str, str]]:
    """Extract (caller_symbol_name, callee_identifier) pairs."""
    calls: List[Tuple[str, str]] = []
    symbol_ranges = sorted(
        [(s.line, s.end_line, s.name) for s in symbols],
        key=lambda x: (x[0], x[1]),
    )

    def _caller_for_line(line: int) -> Optional[str]:
        for start, end, name in symbol_ranges:
            if start <= line <= end:
                return name
        return None

    def walk(node):
        if node.type.endswith("call") or node.type.endswith("call_expression"):
            callee = node.child_by_field_name("function")
            if callee is None:
                for child in node.children:
                    if child.type in ("identifier", "member_expression"):
                        callee = child
                        break
            if callee:
                callee_name = callee.text.decode("utf-8", errors="replace").split("(")[0].split(".")[-1]
                caller_name = _caller_for_line(node.start_point.row + 1)
                if caller_name and caller_name != callee_name:
                    calls.append((caller_name, callee_name))
        for child in node.children:
            walk(child)

    walk(root_node)
    return calls


def _chunk_by_symbols(
    lines: List[str], symbols: List[Symbol], max_lines: int
) -> List[Chunk]:
    if not symbols:
        return _chunk_by_lines(lines, max_lines)

    function_like = [s for s in symbols if s.type in ("function", "method", "class", "interface")]
    if not function_like:
        return _chunk_by_lines(lines, max_lines)

    function_like.sort(key=lambda s: s.line)
    chunks: List[Chunk] = []
    n = len(lines)

    for i, symbol in enumerate(function_like):
        start = symbol.line - 1
        if i + 1 < len(function_like):
            end = function_like[i + 1].line - 1
        else:
            end = n
        end = min(max(end, start + 1), n)

        # If symbol body is too long, split into fixed-size chunks
        if end - start > max_lines:
            for chunk_start in range(start, end, max_lines):
                chunk_end = min(chunk_start + max_lines, end)
                chunk_lines = lines[chunk_start:chunk_end]
                chunks.append(
                    Chunk(
                        content="\n".join(chunk_lines),
                        start_line=chunk_start + 1,
                        end_line=chunk_end,
                        symbols=[s for s in symbols if chunk_start < s.line <= chunk_end],
                    )
                )
        else:
            chunk_lines = lines[start:end]
            chunks.append(
                Chunk(
                    content="\n".join(chunk_lines),
                    start_line=start + 1,
                    end_line=end,
                    symbols=[s for s in symbols if start < s.line <= end],
                )
            )

    return chunks


def _chunk_by_lines(lines: List[str], max_lines: int) -> List[Chunk]:
    chunks: List[Chunk] = []
    n = len(lines)
    for i in range(0, n, max_lines):
        end = min(i + max_lines, n)
        chunks.append(
            Chunk(
                content="\n".join(lines[i:end]),
                start_line=i + 1,
                end_line=end,
            )
        )
    return chunks


def parse_file(file_path: str, content: str, max_chunk_lines: int = 200) -> Optional[ParseResult]:
    """Parse source code and extract symbols, chunks and call edges."""
    language = detect_language(file_path)
    if language is None:
        return None

    lang = _load_language(language)
    if lang is None:
        logger.warning("Language binding unavailable: %s", language)
        return None

    try:
        parser = Parser(lang)
        tree = parser.parse(content.encode("utf-8"))
        root = tree.root_node

        symbols = _extract_symbols(root, language)
        calls = _extract_calls(root, symbols)
        lines = content.split("\n")
        chunks = _chunk_by_symbols(lines, symbols, max_chunk_lines)

        return ParseResult(
            file_path=file_path,
            language=language,
            symbols=symbols,
            chunks=chunks,
            size_bytes=len(content.encode("utf-8")),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            calls=calls,
        )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return None


def list_source_files(repo_path: Path) -> List[Path]:
    """Return all parseable source files under repo_path."""
    files: List[Path] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if should_skip_path(str(path.relative_to(repo_path))):
            continue
        if detect_language(str(path)):
            files.append(path)
    return files
