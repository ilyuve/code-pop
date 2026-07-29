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
from schemas import SearchResultItem
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

    def test_execute_strategy_receives_expanded_terms(self, searcher):
        from services.query_intent import QueryIntent, SearchStrategy

        repo_id = uuid4()
        intent = QueryIntent(
            original="骑士配送",
            intent_type="general",
            is_chinese=True,
            expanded_terms=["骑士配送", "骑手配送", "rider配送"],
            search_strategy=SearchStrategy(primary="bm25", secondary="symbol"),
        )

        searcher._execute_strategy = MagicMock(return_value=[])
        searcher._infer_file_role = MagicMock(return_value="service")

        searcher.search_with_context("骑士配送", repo_id=repo_id, intent=intent)

        passed_intent = searcher._execute_strategy.call_args[0][0]
        assert passed_intent.expanded_terms == ["骑士配送", "骑手配送", "rider配送"]

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
