"""Repository indexing orchestration: git -> parse -> embed -> store with degradation fallback."""

import asyncio
import gc
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from models import CallGraphEdge, CodeFile, Embedding, FrameworkRoute, IndexingLog, IndexingProgress, RepoStatus, Repository, Symbol
from services.embedder import Embedder
from services.degradation_tracker import get_degradation_tracker
from services.notifier import notifier
from services.parser import (
    ParseResult,
    detect_language,
    is_binary,
    list_source_files,
    parse_file,
    should_skip_path,
)
from services.router_parser import RouterParser
from services.repo_sync import clone_or_pull

logger = logging.getLogger(__name__)

# Isolated executor for CPU-bound parsing and embedding.
_index_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexer-")

# Track active indexing tasks per repository.
_active_indexing_tasks: Dict[str, asyncio.Future] = {}
_indexing_locks: Dict[str, asyncio.Lock] = {}

# Store indexing logs per repository.
_indexing_logs: Dict[str, List[Dict[str, Any]]] = {}


def _get_indexing_lock(repo_id: str) -> asyncio.Lock:
    """Get or create a lock for a repository's indexing task."""
    if repo_id not in _indexing_locks:
        _indexing_locks[repo_id] = asyncio.Lock()
    return _indexing_locks[repo_id]


def _cancel_indexing(repo_id: str) -> bool:
    """Cancel an ongoing indexing task for a repository."""
    task = _active_indexing_tasks.get(repo_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def _clear_indexing_state(repo_id: str) -> None:
    """Clean up indexing state for a repository."""
    if repo_id in _active_indexing_tasks:
        del _active_indexing_tasks[repo_id]


def _get_indexing_logs(repo_id: str) -> List[Dict[str, Any]]:
    """Get indexing logs for a repository."""
    return _indexing_logs.get(repo_id, [])


def _clear_indexing_logs(repo_id: str) -> None:
    """Clear indexing logs for a repository."""
    if repo_id in _indexing_logs:
        del _indexing_logs[repo_id]


def _add_log(db: Optional[Session], repo_id: str, level: str, message: str, stage: Optional[str] = None) -> None:
    """Add an indexing log entry for a repository (both in-memory and database)."""
    if repo_id not in _indexing_logs:
        _indexing_logs[repo_id] = []
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "message": message,
        "stage": stage,
    }
    _indexing_logs[repo_id].append(log_entry)
    print(f"[INDEXER LOG] {level.upper()} [{stage}] {message}", flush=True)
    
    if db:
        try:
            db_log = IndexingLog(
                repo_id=UUID(repo_id),
                level=level,
                stage=stage,
                message=message,
            )
            db.add(db_log)
            db.flush()
            db.commit()
        except Exception as exc:
            logger.warning("Failed to write log to database: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass


def _update_progress(db: Session, repo_id: str, stage: str, progress: int, current: int, total: int, status: str, message: Optional[str] = None) -> None:
    """Update indexing progress in the database."""
    try:
        existing = db.query(IndexingProgress).filter(
            IndexingProgress.repo_id == UUID(repo_id),
            IndexingProgress.stage == stage
        ).first()
        
        if existing:
            existing.progress = progress
            existing.current = current
            existing.total = total
            existing.status = status
            if message:
                existing.message = message
        else:
            db.add(IndexingProgress(
                repo_id=UUID(repo_id),
                stage=stage,
                progress=progress,
                current=current,
                total=total,
                status=status,
                message=message,
            ))
        db.flush()
        db.commit()
        logger.info(f"Progress updated: {repo_id} - {stage}: {progress}%")
    except Exception as exc:
        logger.warning("Failed to update progress: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _notify(
    loop: asyncio.AbstractEventLoop,
    repo_id: str,
    status: str,
    progress: float,
    error: Optional[str] = None,
    stage: Optional[str] = None,
    stage_progress: Optional[dict] = None,
    log_message: Optional[str] = None,
    log_level: str = "info",
    db: Optional[Session] = None,
) -> None:
    """Schedule a WebSocket notification on the main event loop from a worker thread."""
    if log_message:
        _add_log(db, repo_id, log_level, log_message, stage)
    
    if db and stage:
        _update_progress(
            db,
            repo_id,
            stage,
            int(progress),
            stage_progress.get("current", 0) if stage_progress else 0,
            stage_progress.get("total", 0) if stage_progress else 0,
            status,
            log_message,
        )
    
    try:
        asyncio.run_coroutine_threadsafe(
            notifier.send_repo_update(
                repo_id, status, progress, error, stage=stage, stage_progress=stage_progress,
                log_message=log_message, log_level=log_level
            ),
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
    """Index a single source file with degradation fallback. Returns inserted CodeFile and parse result."""
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

    parsed = None
    try:
        parsed = parse_file(rel_path, content, settings.index_chunk_max_lines)
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", rel_path, e)
        get_degradation_tracker().record(
            component="indexer",
            error_type="TreeSitterParseError",
            error_message=str(e),
            fallback_action="Trying py_parser fallback",
        )

    if parsed is None and rel_path.endswith(".py"):
        try:
            from services.py_parser import parse_python
            parsed = parse_python(rel_path, content, settings.index_chunk_max_lines)
            logger.info("Fallback to py_parser succeeded for %s", rel_path)
        except Exception as e:
            logger.warning("py_parser also failed for %s: %s", rel_path, e)
            get_degradation_tracker().record(
                component="indexer",
                error_type="PyParserError",
                error_message=str(e),
                fallback_action="Falling back to pure text chunks",
            )

    if parsed is None:
        logger.warning("All parsers failed for %s, storing as text only", rel_path)
        import hashlib
        from services.parser import ParseResult, _chunk_by_lines
        size_bytes = len(content.encode("utf-8"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lines = content.split("\n")
        chunks = _chunk_by_lines(lines, settings.index_chunk_max_lines)
        parsed = ParseResult(
            file_path=rel_path,
            language=detect_language(rel_path) or "unknown",
            symbols=[],
            chunks=chunks,
            size_bytes=size_bytes,
            content_hash=content_hash,
            calls=[],
        )

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
    repo_id_str: str,
    file_records: List[Tuple[CodeFile, ParseResult]],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Embed chunks and bulk insert symbols + embeddings for parsed files."""
    logger.info(
        "Bulk inserting %d parsed files for repo %s",
        len(file_records),
        repo_id,
    )
    if not file_records:
        return

    batch_size = settings.index_batch_size

    # ---- Stage 2: symbol parsing (35% -> 55%) ----
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

    total_symbols = len(symbol_mappings)
    logger.info("Inserting %d symbols", total_symbols)
    if not symbol_mappings:
        _notify(
                loop,
                repo_id_str,
                RepoStatus.indexing.value,
                55.0,
                stage="symbols",
                stage_progress={
                    "stage": "symbols",
                    "current": 0,
                    "total": 0,
                    "percentage": 100.0,
                },
                db=db,
            )
    else:
        for i in range(0, total_symbols, batch_size):
            batch = symbol_mappings[i : i + batch_size]
            db.bulk_insert_mappings(Symbol, batch)
            db.flush()
            inserted = min(i + batch_size, total_symbols)
            pct = (inserted / total_symbols * 100.0) if total_symbols else 100.0
            overall = 35.0 + (inserted / total_symbols * 20.0) if total_symbols else 55.0
            _notify(
                loop,
                repo_id_str,
                RepoStatus.indexing.value,
                overall,
                stage="symbols",
                stage_progress={
                    "stage": "symbols",
                    "current": inserted,
                    "total": total_symbols,
                    "percentage": round(pct, 2),
                },
                db=db,
            )

    # ---- Stage 3: vector generation (55% -> 80%) ----
    embedding_mappings: List[Dict[str, Any]] = []
    texts_to_embed: List[str] = []
    meta: List[Tuple[UUID, int, int, int, int]] = []  # (file_id, chunk_index, start_line, end_line, token_count)

    for code_file, parsed in file_records:
        for idx, chunk in enumerate(parsed.chunks):
            texts_to_embed.append(chunk.content)
            meta.append((code_file.id, idx, chunk.start_line, chunk.end_line, len(chunk.content.split())))

    total_chunks = len(texts_to_embed)
    logger.info("Encoding %d chunks", total_chunks)
    _notify(
        loop,
        repo_id_str,
        RepoStatus.indexing.value,
        55.0,
        stage="embeddings",
        stage_progress={
            "stage": "embeddings",
            "current": 0,
            "total": total_chunks,
            "percentage": 0.0,
        },
        log_message=f"开始生成向量，共 {total_chunks} 个 chunks",
        db=db,
    )

    if not texts_to_embed:
        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            80.0,
            stage="embeddings",
            stage_progress={
                "stage": "embeddings",
                "current": 0,
                "total": 0,
                "percentage": 100.0,
            },
            log_message="无 chunks 需要编码",
            db=db,
        )
        return

    embedder = Embedder()
    encode_batch_size = min(64, total_chunks)
    vectors: List[Any] = []

    for i in range(0, total_chunks, encode_batch_size):
        try:
            import psutil
            available_mb = psutil.virtual_memory().available / (1024 * 1024)
            if available_mb < 500 and encode_batch_size > 1:
                encode_batch_size = max(1, encode_batch_size // 2)
                logger.warning(
                    "Low memory detected (%.0f MB available), reducing batch size to %d",
                    available_mb,
                    encode_batch_size,
                )
                get_degradation_tracker().record(
                    component="indexer",
                    error_type="LowMemory",
                    error_message=f"Available memory {available_mb:.0f} MB < 500 MB",
                    fallback_action=f"Reducing batch size to {encode_batch_size}",
                )
        except ImportError:
            pass

        batch_texts = texts_to_embed[i : i + encode_batch_size]
        batch_vectors = embedder.encode(batch_texts)
        vectors.extend(batch_vectors)
        
        encoded = min(i + encode_batch_size, total_chunks)
        encode_pct = (encoded / total_chunks * 100.0) if total_chunks else 100.0
        encode_overall = 55.0 + (encoded / total_chunks * 12.5)
        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            encode_overall,
            stage="embeddings",
            stage_progress={
                "stage": "embeddings",
                "current": encoded,
                "total": total_chunks,
                "percentage": round(encode_pct, 2),
            },
            log_message=f"已编码 {encoded}/{total_chunks} chunks",
            db=db,
        )

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
    total_embeddings = len(embedding_mappings)
    _notify(
        loop,
        repo_id_str,
        RepoStatus.indexing.value,
        67.5,
        stage="embeddings",
        stage_progress={
            "stage": "embeddings",
            "current": 0,
            "total": total_embeddings,
            "percentage": 0.0,
        },
        log_message=f"开始插入向量，共 {total_embeddings} 条",
        db=db,
    )

    for i in range(0, total_embeddings, batch_size):
        batch = embedding_mappings[i : i + batch_size]
        db.bulk_insert_mappings(Embedding, batch)
        db.flush()
        inserted = min(i + batch_size, total_embeddings)
        pct = (inserted / total_embeddings * 100.0) if total_embeddings else 100.0
        overall = 67.5 + (inserted / total_embeddings * 12.5) if total_embeddings else 80.0
        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            overall,
            stage="embeddings",
            stage_progress={
                "stage": "embeddings",
                "current": inserted,
                "total": total_embeddings,
                "percentage": round(pct, 2),
            },
            log_message=f"已插入 {inserted}/{total_embeddings} 条向量",
            db=db,
        )

    _notify(
        loop,
        repo_id_str,
        RepoStatus.indexing.value,
        80.0,
        stage="embeddings",
        stage_progress={
            "stage": "embeddings",
            "current": total_embeddings,
            "total": total_embeddings,
            "percentage": 100.0,
        },
        log_message="向量生成完成",
        db=db,
    )


def _rebuild_call_graph(
    db: Session,
    repo_id: UUID,
    repo_id_str: str,
    file_records: List[Tuple[CodeFile, ParseResult]],
    loop: asyncio.AbstractEventLoop,
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
        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            100.0,
            stage="call_graph",
            stage_progress={
                "stage": "call_graph",
                "current": 0,
                "total": 0,
                "percentage": 100.0,
            },
            db=db,
        )
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
        total_edges = len(edges)
        for i in range(0, total_edges, batch_size):
            db.bulk_insert_mappings(CallGraphEdge, edges[i : i + batch_size])
            db.flush()
            inserted = min(i + batch_size, total_edges)
            pct = (inserted / total_edges * 100.0) if total_edges else 100.0
            overall = 80.0 + (inserted / total_edges * 20.0) if total_edges else 100.0
            _notify(
                loop,
                repo_id_str,
                RepoStatus.indexing.value,
                overall,
                stage="call_graph",
                stage_progress={
                    "stage": "call_graph",
                    "current": inserted,
                    "total": total_edges,
                    "percentage": round(pct, 2),
                },
                db=db,
            )
    else:
        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            100.0,
            stage="call_graph",
            stage_progress={
                "stage": "call_graph",
                "current": 0,
                "total": 0,
                "percentage": 100.0,
            },
            db=db,
        )


def _sync_index_repo(repo_id: UUID, loop: asyncio.AbstractEventLoop) -> None:
    """Synchronous indexing routine executed in a worker thread."""
    db = SessionLocal()
    repo_id_str = str(repo_id)
    file_records: List[Tuple[CodeFile, ParseResult]] = []
    all_file_records: List[Tuple[CodeFile, ParseResult]] = []
    total_inserted = 0

    try:
        _clear_indexing_logs(repo_id_str)
        _add_log(db, repo_id_str, "info", "开始索引流程", "init")

        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            error_msg = f"Repository {repo_id} not found"
            logger.error(error_msg)
            _add_log(db, repo_id_str, "error", error_msg, "init")
            return

        repo.status = RepoStatus.indexing.value
        repo.error_message = None
        db.commit()
        _notify(loop, repo_id_str, RepoStatus.indexing.value, 0.0, log_message="初始化索引状态", db=db)

        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            5.0,
            stage="git_sync",
            stage_progress={
                "stage": "git_sync",
                "current": 0,
                "total": 1,
                "percentage": 0.0,
            },
            log_message="开始同步代码仓库",
            db=db,
        )

        try:
            local_path = clone_or_pull(repo.name, repo.git_url, repo.local_path)
            repo.local_path = str(local_path)
            db.commit()
            _notify(
                loop,
                repo_id_str,
                RepoStatus.indexing.value,
                10.0,
                stage="git_sync",
                stage_progress={
                    "stage": "git_sync",
                    "current": 1,
                    "total": 1,
                    "percentage": 100.0,
                },
                log_message=f"代码同步完成，本地路径: {local_path}",
                db=db,
            )
        except Exception as sync_exc:
            error_msg = f"代码同步失败: {str(sync_exc)}"
            _add_log(db, repo_id_str, "error", error_msg, "git_sync")
            raise

        source_files = list_source_files(local_path)
        total = len(source_files)
        processed = 0
        skipped = 0

        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            10.0,
            stage="scan",
            stage_progress={
                "stage": "scan",
                "current": 0,
                "total": total,
                "percentage": 0.0,
            },
            log_message=f"开始扫描文件，共发现 {total} 个源文件",
            db=db,
        )

        for file_path in source_files:
            try:
                result = _index_file(db, repo_id, local_path, file_path)
                if result:
                    file_records.append(result)
                    all_file_records.append(result)
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("Failed to index %s: %s", file_path.relative_to(local_path), exc)
                _add_log(db, repo_id_str, "warning", f"文件索引失败 {file_path.relative_to(local_path)}: {str(exc)}", "scan")
                skipped += 1

            processed += 1

            if processed % 10 == 0 or processed == total:
                scan_pct = (processed / total * 100.0) if total else 100.0
                overall = 10.0 + (processed / total * 25.0) if total else 35.0
                _notify(
                    loop,
                    repo_id_str,
                    RepoStatus.indexing.value,
                    overall,
                    stage="scan",
                    stage_progress={
                        "stage": "scan",
                        "current": processed,
                        "total": total,
                        "percentage": round(scan_pct, 2),
                    },
                    log_message=f"文件扫描进度: {processed}/{total}",
                    db=db,
                )

        _add_log(db, repo_id_str, "info", f"文件扫描完成，共处理 {processed} 个文件，跳过 {skipped} 个", "scan")

        if all_file_records:
            print(f"[INDEXER] flushing {len(all_file_records)} records for repo {repo_id}", flush=True)
            _bulk_insert_symbols_and_embeddings(db, repo_id, repo_id_str, all_file_records, loop)
            total_inserted += len(all_file_records)
            db.commit()
            db.expire_all()
            gc.collect()

        _notify(
            loop,
            repo_id_str,
            RepoStatus.indexing.value,
            80.0,
            stage="call_graph",
            stage_progress={
                "stage": "call_graph",
                "current": 0,
                "total": 1,
                "percentage": 0.0,
            },
            log_message="开始构建调用图",
            db=db,
        )

        _rebuild_call_graph(db, repo_id, repo_id_str, all_file_records, loop)
        db.commit()

        _add_log(db, repo_id_str, "info", "调用图构建完成", "call_graph")

        _parse_framework_routes(db, repo_id, repo_id_str, all_file_records, loop)
        db.commit()

        _add_log(db, repo_id_str, "info", "框架路由解析完成", "routes")

        repo.status = RepoStatus.indexed.value
        repo.last_indexed_at = datetime.utcnow()
        db.commit()

        _notify(loop, repo_id_str, RepoStatus.indexed.value, 100.0, log_message="索引完成", db=db)
        _add_log(db, repo_id_str, "info", f"索引完成: {total} 个文件处理，{total_inserted} 个插入/更新，{skipped} 个跳过", "complete")

        logger.info(
            "Indexed repository %s: %d files processed, %d inserted/updated, %d skipped",
            repo_id,
            total,
            total_inserted,
            skipped,
        )

    except Exception as exc:
        logger.exception("Failed to index repository %s: %s", repo_id, exc)
        full_traceback = traceback.format_exc()
        error_msg = str(exc)
        _add_log(db, repo_id_str, "error", f"索引失败: {error_msg}", "error")
        _add_log(db, repo_id_str, "error", f"详细堆栈:\n{full_traceback}", "error")
        
        try:
            repo = db.query(Repository).filter(Repository.id == repo_id).first()
            if repo:
                repo.status = RepoStatus.error.value
                repo.error_message = error_msg
                db.commit()
            _notify(loop, repo_id_str, RepoStatus.error.value, 0.0, error_msg, db=db)
        except Exception:
            pass
    finally:
        _clear_indexing_state(repo_id_str)
        db.close()


async def index_repo(repo_id: UUID) -> None:
    """Public async entry point to index a repository in the background."""
    repo_id_str = str(repo_id)
    loop = asyncio.get_running_loop()
    
    lock = _get_indexing_lock(repo_id_str)
    
    async with lock:
        if _cancel_indexing(repo_id_str):
            logger.info("Cancelled existing indexing task for repo %s", repo_id_str)
        
        def _run_index():
            _sync_index_repo(repo_id, loop)
        
        task = loop.run_in_executor(
            _index_executor,
            _run_index,
        )
        _active_indexing_tasks[repo_id_str] = task
        
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Indexing task cancelled for repo %s", repo_id_str)
        except Exception as exc:
            logger.exception("Indexing task failed for repo %s: %s", repo_id_str, exc)
        finally:
            _clear_indexing_state(repo_id_str)


def shutdown_indexer() -> None:
    """Gracefully shut down the background indexing executor."""
    for repo_id, task in list(_active_indexing_tasks.items()):
        if not task.done():
            task.cancel()
    _index_executor.shutdown(wait=True)


def _parse_framework_routes(
    db: Session,
    repo_id: UUID,
    repo_id_str: str,
    file_records: List[Tuple[CodeFile, ParseResult]],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """解析框架路由并写入数据库。"""
    router_parser = RouterParser()
    total_routes = 0

    db.query(FrameworkRoute).filter(FrameworkRoute.repo_id == repo_id).delete(synchronize_session=False)

    for code_file, parsed in file_records:
        if parsed.language in ("python", "javascript", "typescript", "java"):
            try:
                routes = router_parser.parse(parsed.content, parsed.language)
                for route in routes:
                    db_route = FrameworkRoute(
                        repo_id=repo_id,
                        file_id=code_file.id,
                        framework=route.framework,
                        http_method=route.method,
                        path=route.path,
                        handler_symbol=route.handler,
                        line_number=route.line,
                    )
                    db.add(db_route)
                    total_routes += 1
            except Exception as e:
                logger.warning("Route parsing failed for %s: %s", code_file.path, e)
                get_degradation_tracker().record(
                    component="indexer",
                    error_type="RouteParseError",
                    error_message=str(e),
                    fallback_action="Skipping route parsing for this file",
                )

    logger.info("Parsed %d framework routes for repo %s", total_routes, repo_id)


__all__ = ["index_repo", "shutdown_indexer", "_get_indexing_logs", "_cancel_indexing"]
