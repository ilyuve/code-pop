"""Integration-level tests for Chinese semantic retrieval features."""

import asyncio
import json
import threading
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main import app
from schemas import CodeContext, SearchResultItem
from api import search as search_api
from services.indexer import (
    IndexingCancelledError,
    _cancel_indexing,
    _check_cancelled,
    _clear_indexing_state,
    _get_cancel_event,
    _is_cancelled,
)
from services.llm_router import LLMRouter
from services.query_intent import QueryIntent, SearchStrategy, expand_query_with_synonyms
from services.searcher import Searcher


class TestTimezoneAwareResponse:
    def test_naive_utc_datetime_includes_offset(self):
        """Naive datetimes stored as UTC must serialize with +00:00 so JS
        Date.parse/toLocaleString converts to local time automatically."""
        from main import _TimezoneAwareJSONResponse

        response = _TimezoneAwareJSONResponse(
            content={"ts": datetime(2026, 7, 29, 18, 47, 31)}
        )
        body = json.loads(response.body)
        assert body["ts"].endswith("+00:00")


class TestLLMRouterUsageLogSessionIsolation:
    def test_write_usage_log_uses_fresh_session(self):
        """_write_usage_log must not commit/rollback the router's shared session."""
        db = MagicMock()
        router = LLMRouter(db)

        with patch("services.llm_router.SessionLocal") as mock_session_local:
            log_session = MagicMock()
            mock_session_local.return_value = log_session

            router._write_usage_log(
                provider_id=str(uuid4()),
                repo_id=str(uuid4()),
                operation="chat",
                status="success",
                input_tokens=10,
                output_tokens=5,
                latency_ms=100,
            )

            # The router's own session should never be touched for writes.
            db.add.assert_not_called()
            db.commit.assert_not_called()
            db.rollback.assert_not_called()

            # A dedicated session should have been opened and committed.
            mock_session_local.assert_called_once()
            log_session.add.assert_called_once()
            log_session.commit.assert_called_once()
            log_session.close.assert_called_once()


class TestCancelIndexing:
    def test_cancel_event_is_created_and_set(self):
        repo_id = str(uuid4())
        _clear_indexing_state(repo_id)

        # First cancel sets the event and returns True.
        assert _cancel_indexing(repo_id) is True
        assert _is_cancelled(repo_id) is True

        # Calling again on an already cancelled repo returns False.
        assert _cancel_indexing(repo_id) is False

        _clear_indexing_state(repo_id)

    def test_check_cancelled_raises_after_cancel(self):
        repo_id = str(uuid4())
        _clear_indexing_state(repo_id)
        _cancel_indexing(repo_id)

        with pytest.raises(IndexingCancelledError):
            _check_cancelled(repo_id)

        _clear_indexing_state(repo_id)

    def test_check_cancelled_passes_when_not_cancelled(self):
        repo_id = str(uuid4())
        _clear_indexing_state(repo_id)
        _check_cancelled(repo_id)  # should not raise
        _clear_indexing_state(repo_id)


class TestChineseSynonymExpansion:
    def test_synonym_expansion_includes_variants(self):
        synonyms = {
            "骑士": ["骑手", "配送员"],
            "配送": ["送货", "派送"],
        }
        variants = expand_query_with_synonyms("骑士配送流程", synonyms)

        # Current implementation expands one term at a time.
        assert "骑士配送流程" in variants
        assert "骑手配送流程" in variants
        assert "配送员配送流程" in variants
        assert "骑士送货流程" in variants
        assert "骑士派送流程" in variants

    def test_query_intent_carries_expanded_terms(self):
        intent = QueryIntent(
            original="骑士配送流程",
            intent_type="general",
            is_chinese=True,
            expanded_terms=["骑士配送流程", "骑手配送流程", "rider配送流程"],
            search_strategy=SearchStrategy(primary="bm25", secondary="symbol"),
        )
        assert "骑手配送流程" in intent.expanded_terms


class TestSearcherUsesExpandedTerms:
    @pytest.fixture
    def searcher(self):
        db = MagicMock()
        with patch("services.searcher.Embedder") as mock_embedder_cls:
            mock_embedder = MagicMock()
            mock_embedder.encode_query.return_value = [0.1] * 1024
            mock_embedder.encode_query_sparse.return_value = {1: 0.5}
            mock_embedder_cls.return_value = mock_embedder
            yield Searcher(db)

    def test_unified_pipeline_used_with_expanded_terms(self, searcher):
        from services.query_intent import QueryIntent, SearchStrategy

        repo_id = uuid4()
        intent = QueryIntent(
            original="骑士配送",
            intent_type="general",
            is_chinese=True,
            expanded_terms=["骑士配送", "骑手配送", "rider配送"],
            search_strategy=SearchStrategy(primary="bm25", secondary="symbol"),
        )

        searcher._search_and_fuse = MagicMock(return_value=[])
        searcher._infer_file_role = MagicMock(return_value="service")

        context = searcher.search_with_context("骑士配送", repo_id=repo_id, intent=intent)

        # The unified RRF pipeline is called with the original query plus the
        # expanded terms, and the expanded terms flow into matched concepts.
        searcher._search_and_fuse.assert_called_once_with(
            "骑士配送", repo_id, 20,
            search_terms=["骑士配送", "骑手配送", "rider配送"],
            path_overrides=None,
            trace=None,
        )
        assert "骑手配送" in context.matched_concepts

    def test_bm25_search_query_text_passed_as_param(self, searcher):
        repo_id = uuid4()
        searcher.db.execute.return_value.fetchall.return_value = []

        query_text = "骑士配送 骑手配送 rider配送"
        searcher._bm25_search(query_text, repo_id)

        call_args = searcher.db.execute.call_args
        # execute(sql, params) -> positional args: (sql, params)
        params = call_args[0][1]
        # SQL is parameterized; the query text should appear in the bound parameters.
        assert params["query"] == query_text


class TestDeleteRepo:
    def test_delete_cancels_indexing_and_cleans_related_records(self):
        """Deleting an indexing repository must cancel indexing and remove all
        related rows without relying on FK cascades alone."""
        from api.repos import delete_repo
        from models import (
            DomainSynonym,
            FrameworkRoute,
            IndexingLog,
            IndexingProgress,
            LlmSetting,
            RepoStatus,
            Repository,
        )

        repo_id = uuid4()
        repo = Repository(
            id=repo_id,
            name="test-repo",
            git_url="https://github.com/example/test-repo",
            local_path="/tmp/test-repo",
            status=RepoStatus.indexing.value,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = repo
        db.query.return_value.filter.return_value.delete.return_value = None

        with patch("api.repos._cancel_indexing") as mock_cancel, \
             patch("api.repos._clear_indexing_state") as mock_clear_state, \
             patch("api.repos._clear_indexing_logs") as mock_clear_logs:
            delete_repo(repo_id, db=db)

        mock_cancel.assert_called_once_with(str(repo_id))
        db.delete.assert_called_once_with(repo)
        db.commit.assert_called_once()
        mock_clear_state.assert_called_once_with(str(repo_id))
        mock_clear_logs.assert_called_once_with(str(repo_id))

        # Ensure all related tables are cleaned up explicitly.
        cleanup_models = [
            IndexingProgress,
            IndexingLog,
            FrameworkRoute,
            DomainSynonym,
            LlmSetting,
        ]
        queried_models = [call[0][0] for call in db.query.call_args_list]
        for model in cleanup_models:
            assert model in queried_models

    def test_delete_nonexistent_repo_raises_404(self):
        from api.repos import delete_repo
        from exceptions import RepoNotFoundException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(RepoNotFoundException):
            delete_repo(uuid4(), db=db)


class TestForceReindexWhenEnrichmentMissing:
    def test_reindexes_when_hash_matches_but_enrichment_missing(self, tmp_path):
        """If a file hash matches but the previous run skipped Chinese enrichment,
        _index_file must delete the stale row and re-process the file."""
        import hashlib

        from models import CodeFile, Embedding, EmbeddingEnrichment, Symbol as SymbolModel
        from services.indexer import _index_file
        from services.parser import Chunk, ParseResult, Symbol

        repo_id = uuid4()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        file_path = repo_path / "src" / "order.py"
        file_path.parent.mkdir()
        content = "def create_order(): pass"
        file_path.write_text(content, encoding="utf-8")
        content_bytes = content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        existing = CodeFile(
            id=uuid4(),
            repo_id=repo_id,
            path="src/order.py",
            language="python",
            content_hash=content_hash,
            size_bytes=len(content_bytes),
        )

        db = MagicMock()

        def _query_side_effect(model):
            q = MagicMock()
            if model is CodeFile:
                q.filter.return_value.first.return_value = existing
            elif model is SymbolModel.id:
                q.filter.return_value.first.return_value = MagicMock()
            elif model is Embedding.id:
                q.filter.return_value.first.return_value = MagicMock()
            elif model is EmbeddingEnrichment.id:
                join_mock = MagicMock()
                join_mock.filter.return_value.first.return_value = None
                q.join.return_value = join_mock
            return q

        db.query.side_effect = _query_side_effect

        parsed = ParseResult(
            file_path="src/order.py",
            language="python",
            symbols=[
                Symbol(
                    name="create_order",
                    type="function",
                    kind="def",
                    line=1,
                    column=0,
                    end_line=1,
                    end_column=len(content),
                    is_exported=True,
                )
            ],
            chunks=[Chunk(content=content, start_line=1, end_line=1)],
            size_bytes=len(content_bytes),
            content_hash=content_hash,
            calls=[],
        )

        with patch("services.indexer.parse_file", return_value=parsed):
            result = _index_file(db, repo_id, repo_path, file_path)

        assert result is not None
        code_file, parse_result = result
        assert code_file.path == "src/order.py"
        assert parse_result.content_hash == content_hash
        db.delete.assert_called_once_with(existing)


class TestIndexingStateRecovery:
    def test_recover_indexing_repos_resets_to_pending(self):
        """After a server restart, repos stuck in indexing state must be reset to
        pending so the UI does not stay frozen."""
        from main import _recover_indexing_repos
        from models import RepoStatus, Repository

        repo1 = Repository(
            id=uuid4(),
            name="repo1",
            status=RepoStatus.indexing.value,
            indexing_heartbeat_at=datetime(2026, 7, 29, 18, 0, 0),
        )
        repo2 = Repository(
            id=uuid4(),
            name="repo2",
            status=RepoStatus.indexed.value,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [repo1]

        with patch("main.SessionLocal", return_value=db):
            asyncio.run(_recover_indexing_repos())

        assert repo1.status == RepoStatus.pending.value
        assert repo1.error_message is None
        assert repo1.indexing_heartbeat_at is None
        db.commit.assert_called_once()


class TestDebugSearchConsistency:
    """Debug endpoint must return the same final context as /search/context."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        app.dependency_overrides[search_api.get_db] = lambda: db
        yield db
        app.dependency_overrides.clear()

    def test_debug_and_context_return_same_final_snippets(self, client, mock_db):
        repo_id = uuid4()
        snippet_id = uuid4()
        file_id = uuid4()

        fake_context = SearchResultItem(
            id=snippet_id,
            file_id=file_id,
            repo_id=repo_id,
            repo_name="test-repo",
            file_path="src/order.py",
            language="python",
            content="def create_order(): pass",
            line=1,
            score=0.95,
            score_breakdown={"vector": 0.9, "final": 0.95},
        )

        fake_code_context = CodeContext(
            query="订单创建流程",
            query_intent="general",
            matched_concepts=["订单", "order"],
            entry_points=[],
            call_chain=None,
            flow_summary=None,
            related_files=[],
            code_snippets=[fake_context],
            total_files=1,
            total_symbols=0,
        )

        with patch("api.search.Searcher") as mock_searcher_cls:
            instance = MagicMock()
            instance.search_with_context.return_value = fake_code_context
            instance.debug_search.return_value = (
                fake_code_context,
                MagicMock(
                    query_analysis={},
                    paths=[],
                    fusion={
                        "rrf_k": 60,
                        "hit_count": 1,
                        "hits": [{"id": str(snippet_id), "score": 0.95}],
                    },
                    rerank={
                        "code_reranker": {
                            "input_count": 1,
                            "output_count": 1,
                            "output": [{"id": str(snippet_id), "score": 0.95}],
                        },
                        "m3_reranker": {
                            "input_count": 1,
                            "output_count": 1,
                            "output": [{"id": str(snippet_id), "score": 0.95}],
                        },
                    },
                    final_context=fake_code_context,
                ),
            )
            mock_searcher_cls.return_value = instance

            context_resp = client.post("/api/search/context", json={
                "query": "订单创建流程",
                "repo_id": str(repo_id),
                "limit": 20,
            })
            debug_resp = client.post("/api/search/debug", json={
                "query": "订单创建流程",
                "repo_id": str(repo_id),
                "limit": 20,
            })

        assert context_resp.status_code == 200
        assert debug_resp.status_code == 200

        context_snippets = context_resp.json()["context"]["code_snippets"]
        debug_snippets = debug_resp.json()["final_context"]["code_snippets"]
        assert len(context_snippets) == len(debug_snippets) == 1
        assert context_snippets[0]["id"] == debug_snippets[0]["id"]
        assert context_snippets[0]["file_path"] == debug_snippets[0]["file_path"]

    def test_debug_endpoint_does_not_record_history(self, client, mock_db):
        repo_id = uuid4()

        fake_code_context = CodeContext(
            query="订单创建流程",
            query_intent="general",
            matched_concepts=[],
            entry_points=[],
            call_chain=None,
            flow_summary=None,
            related_files=[],
            code_snippets=[],
            total_files=0,
            total_symbols=0,
        )

        with patch("api.search.Searcher") as mock_searcher_cls:
            instance = MagicMock()
            instance.debug_search.return_value = (
                fake_code_context,
                MagicMock(
                    query_analysis={},
                    paths=[],
                    fusion={
                        "rrf_k": 60,
                        "hit_count": 0,
                        "hits": [],
                    },
                    rerank={
                        "code_reranker": {
                            "input_count": 0,
                            "output_count": 0,
                            "output": [],
                        },
                        "m3_reranker": {
                            "input_count": 0,
                            "output_count": 0,
                            "output": [],
                        },
                    },
                    final_context=fake_code_context,
                ),
            )
            mock_searcher_cls.return_value = instance

            resp = client.post("/api/search/debug", json={
                "query": "订单创建流程",
                "repo_id": str(repo_id),
                "limit": 20,
            })

        assert resp.status_code == 200
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()
