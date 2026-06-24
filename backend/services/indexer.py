"""Repository indexing orchestration: git -> parse -> embed -> store."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from models import CallGraphEdge, CodeFile, Embedding, RepoStatus, Repository, Symbol
from services.embedder import Embedder
from services.notifier import notifier
from services.parser import (
    ParseResult,
    detect_language,
    is_binary,
    list_source_files,
    parse_file,
    should_skip_path,
)
from services.repo_sync import clone_or_pull

logger = logging.getLogger(__name__)

# Isolated executor for CPU-bound parsing and embedding.
_index_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="indexer-")


def _notify(loop: asyncio.AbstractEventLoop, repo_id: str, status: str, progress: float, error: str | None = None) -> None:
    """Schedule a WebSocket notification on the main event loop from a worker thread."""
    try:
        asyncio.run_coroutine_threadsafe(
            notifier.send_repo_update(repo_id, status, progress, error),
            loop,
        )
    except Exception as exc:
        logger.warning("Failed to send WS notification: %s", exc)


def _read_file(file_path: Path) -> Optional[str]:
    """Read a source file, skipping binaries and oversized files."""
    if file_path.stat().st_size > settings.index_max_file_size:
        logger.debug("Skipping oversized file: %s", file_path)
        return None
    try:
        content_bytes = file_path.read_bytes()
    except Exception as exc:
        logger.warning("Cannot read %s: %s", file_path, exc)
        return None
    if is_binary(content_bytes):
        return None
    return content_bytes.decode("utf-8", errors="replace")


def _index_file(
    db: Session,
    repo_id: UUID,
    repo_path: Path,
    file_path: Path,
) -> Optional[Tuple[CodeFile, ParseResult]]:
    """Index a single source file. Returns inserted CodeFile and parse result."""
    rel_path = str(file_path.relative_to(repo_path))

    if should_skip_path(rel_path):
        return None

    content = _read_file(file_path)
    if content is None:
        print(f"[INDEXER] skip read failed {rel_path}", flush=True)
        return None

    existing = (
        db.query(CodeFile)
        .filter(CodeFile.repo_id == repo_id, CodeFile.path == rel_path)
        .first()
    )

    parsed = parse_file(rel_path, content, settings.index_chunk_max_lines)
    if parsed is None:
        print(f"[INDEXER] parse failed {rel_path}", flush=True)
        return None

    # If an existing file has the same hash, we still need to ensure its
    # symbols and embeddings were actually persisted. A previous interrupted
    # index run may have left orphaned code_files rows.
    if existing and existing.content_hash == parsed.content_hash:
        has_children = (
            db.query(Symbol.id).filter(Symbol.file_id == existing.id).first() is not None
            and db.query(Embedding.id).filter(Embedding.file_id == existing.id).first() is not None
        )
        if has_children:
            print(f"[INDEXER] unchanged {rel_path}", flush=True)
            return None
        print(
            f"[INDEXER] hash match but missing children for {rel_path}, re-indexing",
            flush=True,
        )
        db.delete(existing)
        db.flush()
    elif existing:
        db.delete(existing)
        db.flush()

    language = detect_language(rel_path) or parsed.language
    code_file = CodeFile(
        repo_id=repo_id,
        path=rel_path,
        language=language or "unknown",
        content_hash=parsed.content_hash,
        size_bytes=parsed.size_bytes,
        updated_at=datetime.utcnow(),
    )
    db.add(code_file)
    db.flush()  # obtain code_file.id
    print(f"[INDEXER] inserted {rel_path} symbols={len(parsed.symbols)} chunks={len(parsed.chunks)}", flush=True)

    return code_file, parsed


def _bulk_insert_symbols_and_embeddings(
    db: Session,
    repo_id: UUID,
    file_records: List[Tuple[CodeFile, ParseResult]],
) -> None:
    """Embed chunks and bulk insert symbols + embeddings for parsed files."""
    logger.info(
        "Bulk inserting %d parsed files for repo %s",
        len(file_records),
        repo_id,
    )
    if not file_records:
        return

    embedder = Embedder()

    # Insert symbols first so we can map names to IDs later.
    symbol_mappings: List[Dict[str, Any]] = []
    for code_file, parsed in file_records:
        for sym in parsed.symbols:
            symbol_mappings.append(
                {
                    "file_id": code_file.id,
                    "repo_id": repo_id,
                    "name": sym.name,
                    "type": sym.type,
                    "kind": sym.kind,
                    "line": sym.line,
                    "column": sym.column,
                    "end_line": sym.end_line,
                    "end_column": sym.end_column,
                    "is_exported": 1 if sym.is_exported else 0,
                }
            )

    logger.info("Inserting %d symbols", len(symbol_mappings))
    if symbol_mappings:
        db.bulk_insert_mappings(Symbol, symbol_mappings)
        db.flush()

    # Prepare embedding records.
    embedding_mappings: List[Dict[str, Any]] = []
    texts_to_embed: List[str] = []
    meta: List[Tuple[UUID, int, int, int, int]] = []  # (file_id, chunk_index, start_line, end_line, token_count)

    for code_file, parsed in file_records:
        for idx, chunk in enumerate(parsed.chunks):
            texts_to_embed.append(chunk.content)
            meta.append((code_file.id, idx, chunk.start_line, chunk.end_line, len(chunk.content.split())))

    logger.info("Encoding %d chunks", len(texts_to_embed))
    if not texts_to_embed:
        return

    vectors = embedder.encode(texts_to_embed)
    for text_idx, (vector, mapping_meta) in enumerate(zip(vectors, meta)):
        file_id, chunk_index, start_line, end_line, token_count = mapping_meta
        embedding_mappings.append(
            {
                "file_id": file_id,
                "repo_id": repo_id,
                "chunk_index": chunk_index,
                "start_line": start_line,
                "end_line": end_line,
                "content": texts_to_embed[text_idx],
                "embedding": vector,
                "token_count": token_count,
            }
        )

    # Batch insert embeddings.
    batch_size = settings.index_batch_size
    for i in range(0, len(embedding_mappings), batch_size):
        batch = embedding_mappings[i : i + batch_size]
        db.bulk_insert_mappings(Embedding, batch)
        db.flush()


def _rebuild_call_graph(
    db: Session,
    repo_id: UUID,
    file_records: List[Tuple[CodeFile, ParseResult]],
) -> None:
    """Rebuild call graph edges ONLY for changed files."""
    if not file_records:
        return

    # 1. Collect changed file IDs and symbol names appearing in changed calls.
    changed_file_ids = {code_file.id for code_file, _ in file_records}
    changed_symbol_names: set = set()
    for _, parsed in file_records:
        for caller, callee in parsed.calls:
            changed_symbol_names.add(caller)
            changed_symbol_names.add(callee)

    # 2. Find symbol IDs that belong to changed files OR appear in changed calls.
    symbols_to_update = (
        db.query(Symbol)
        .filter(Symbol.repo_id == repo_id)
        .filter(
            (Symbol.file_id.in_(changed_file_ids))
            | (Symbol.name.in_(list(changed_symbol_names)))
        )
        .all()
    )
    symbol_ids_to_update = {s.id for s in symbols_to_update}

    if not symbol_ids_to_update:
        return

    # 3. Delete ONLY edges where source or target is in the affected set.
    db.query(CallGraphEdge).filter(
        CallGraphEdge.repo_id == repo_id,
        (CallGraphEdge.source_symbol_id.in_(symbol_ids_to_update))
        | (CallGraphEdge.target_symbol_id.in_(symbol_ids_to_update)),
    ).delete(synchronize_session=False)

    # 4. Build name -> id map for ALL symbols in repo (needed for cross-file calls).
    all_symbols = db.query(Symbol).filter(Symbol.repo_id == repo_id).all()
    name_to_ids: Dict[str, List[UUID]] = {}
    for sym in all_symbols:
        name_to_ids.setdefault(sym.name, []).append(sym.id)

    # 5. Insert new edges from changed files only.
    edges: List[Dict[str, Any]] = []
    seen: set = set()

    for code_file, parsed in file_records:
        for caller_name, callee_name in parsed.calls:
            caller_ids = name_to_ids.get(caller_name, [])
            callee_ids = name_to_ids.get(callee_name, [])
            for source_id in caller_ids:
                for target_id in callee_ids:
                    key = (source_id, target_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append(
                        {
                            "source_symbol_id": source_id,
                            "target_symbol_id": target_id,
                            "repo_id": repo_id,
                            "call_type": "direct",
                        }
                    )

    if edges:
        batch_size = settings.index_batch_size
        for i in range(0, len(edges), batch_size):
            db.bulk_insert_mappings(CallGraphEdge, edges[i : i + batch_size])
        db.flush()


def _sync_index_repo(repo_id: UUID, loop: asyncio.AbstractEventLoop) -> None:
    """Synchronous indexing routine executed in a worker thread."""
    db = SessionLocal()
    repo_id_str = str(repo_id)
    file_records: List[Tuple[CodeFile, ParseResult]] = []

    try:
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            logger.error("Repository %s not found", repo_id)
            return

        repo.status = RepoStatus.indexing.value
        db.commit()
        _notify(loop, repo_id_str, RepoStatus.indexing.value, 0.0)

        local_path = clone_or_pull(repo.name, repo.git_url)
        repo.local_path = str(local_path)
        db.commit()

        source_files = list_source_files(local_path)
        total = len(source_files)
        processed = 0
        skipped = 0

        for file_path in source_files:
            try:
                result = _index_file(db, repo_id, local_path, file_path)
                if result:
                    file_records.append(result)
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("Failed to index %s: %s", file_path.relative_to(local_path), exc)
                skipped += 1

            processed += 1
            if processed % 10 == 0 or processed == total:
                progress = (processed / total * 100.0) if total else 100.0
                _notify(loop, repo_id_str, RepoStatus.indexing.value, progress)

        # Keep file_records and their children in a single transaction so an
        # interrupted run cannot leave orphaned code_files rows.
        print(f"[INDEXER] file_records={len(file_records)} for repo {repo_id}", flush=True)
        _bulk_insert_symbols_and_embeddings(db, repo_id, file_records)
        _rebuild_call_graph(db, repo_id, file_records)
        db.commit()

        repo.status = RepoStatus.indexed.value
        repo.last_indexed_at = datetime.utcnow()
        db.commit()

        _notify(loop, repo_id_str, RepoStatus.indexed.value, 100.0)
        logger.info(
            "Indexed repository %s: %d files processed, %d inserted/updated, %d skipped",
            repo_id,
            total,
            len(file_records),
            skipped,
        )

    except Exception as exc:
        logger.exception("Failed to index repository %s: %s", repo_id, exc)
        try:
            repo = db.query(Repository).filter(Repository.id == repo_id).first()
            if repo:
                repo.status = RepoStatus.error.value
                db.commit()
            _notify(loop, repo_id_str, RepoStatus.error.value, 0.0, str(exc))
        except Exception:
            pass
    finally:
        db.close()


async def index_repo(repo_id: UUID) -> None:
    """Public async entry point to index a repository in the background."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        _index_executor,
        _sync_index_repo,
        repo_id,
        loop,
    )


def shutdown_indexer() -> None:
    """Gracefully shut down the background indexing executor."""
    _index_executor.shutdown(wait=True)
