"""Tests for multi-provider LLM routing with fallback."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.llm_client import LLMChatResponse, LLMError, LLMTimeoutError
from services.llm_router import LLMRouter, LLMUnavailableError


from services.llm_client import encrypt_api_key


def _make_provider(name, capability="chat", priority=0, enabled=1):
    p = MagicMock()
    p.id = uuid4()
    p.name = name
    p.capability = capability
    p.priority = priority
    p.enabled = enabled
    p.base_url = "https://api.example.com"
    p.api_key = encrypt_api_key("sk-test")
    p.model = "model"
    p.max_tokens = 1024
    p.temperature = 0.1
    p.timeout_seconds = 30
    p.extra_headers = None
    return p


def _configure_db_query(db, providers):
    """Set up the full SQLAlchemy query chain mock used by LLMRouter."""
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = providers


@pytest.fixture
def db():
    return MagicMock()


@pytest.mark.asyncio
class TestChatRouting:
    async def test_uses_first_available_provider(self, db):
        provider = _make_provider("primary")
        _configure_db_query(db, [provider])

        router = LLMRouter(db)
        expected = LLMChatResponse(
            content="ok",
            input_tokens=1,
            output_tokens=1,
            model="model",
            latency_ms=10,
        )

        with patch.object(
            router, "_try_provider_chat", new=AsyncMock(return_value=(expected, str(provider.id)))
        ):
            resp, pid = await router.chat([{"role": "user", "content": "hi"}])

        assert resp == expected
        assert pid == str(provider.id)

    async def test_falls_back_on_failure(self, db):
        primary = _make_provider("primary", priority=0)
        fallback = _make_provider("fallback", priority=1)
        _configure_db_query(db, [primary, fallback])

        router = LLMRouter(db)
        expected = LLMChatResponse(
            content="fallback ok",
            input_tokens=1,
            output_tokens=1,
            model="model",
            latency_ms=10,
        )

        async def _try(provider, *args, **kwargs):
            if provider.name == "primary":
                raise LLMTimeoutError("primary failed")
            return expected, str(provider.id)

        with patch.object(router, "_try_provider_chat", new=AsyncMock(side_effect=_try)):
            resp, pid = await router.chat([{"role": "user", "content": "hi"}])

        assert resp.content == "fallback ok"
        assert pid == str(fallback.id)

    async def test_raises_when_no_providers(self, db):
        _configure_db_query(db, [])
        router = LLMRouter(db)

        with pytest.raises(LLMUnavailableError):
            await router.chat([{"role": "user", "content": "hi"}])

    async def test_raises_when_all_providers_fail(self, db):
        p1 = _make_provider("p1")
        p2 = _make_provider("p2")
        _configure_db_query(db, [p1, p2])

        router = LLMRouter(db)
        with patch.object(
            router, "_try_provider_chat", new=AsyncMock(side_effect=LLMTimeoutError("fail"))
        ):
            with pytest.raises(LLMUnavailableError):
                await router.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
class TestEmbedRouting:
    async def test_embed_uses_first_provider(self, db):
        provider = _make_provider("embed", capability="embed")
        router = LLMRouter(db)
        expected = [MagicMock(embedding=[0.1], index=0)]

        with patch.object(router, "_get_enabled_providers", return_value=[provider]):
            with patch(
                "services.llm_router.LLMClient.embed", new=AsyncMock(return_value=expected)
            ):
                resp, pid = await router.embed(["hello"])

        assert resp == expected
        assert pid == str(provider.id)

    async def test_embed_skips_chat_only_provider(self, db):
        chat_only = _make_provider("chat-only", capability="chat")
        embed_provider = _make_provider("embed", capability="embed")
        router = LLMRouter(db)
        expected = [MagicMock(embedding=[0.1], index=0)]

        # _get_enabled_providers is responsible for filtering by capability;
        # mock it so only embed-capable providers are returned.
        with patch.object(
            router, "_get_enabled_providers", return_value=[embed_provider]
        ) as mock_get:
            with patch(
                "services.llm_router.LLMClient.embed", new=AsyncMock(return_value=expected)
            ):
                resp, pid = await router.embed(["hello"])

        mock_get.assert_called_once_with("embed")
        assert pid == str(embed_provider.id)


class TestProviderQuery:
    def test_get_enabled_providers_builds_embed_capability_query(self, db):
        """_get_enabled_providers should filter by embed/both capabilities."""
        _configure_db_query(db, [])

        router = LLMRouter(db)
        router._get_enabled_providers("embed")

        query = db.query.return_value
        # First filter: enabled == 1
        assert query.filter.call_count == 1
        enabled_filter_arg = query.filter.call_args[0][0]
        assert "enabled" in str(enabled_filter_arg).lower()

        # Second filter: capability in ('embed', 'both')
        capability_query = query.filter.return_value
        assert capability_query.filter.call_count == 1
        capability_filter_arg = capability_query.filter.call_args[0][0]
        rendered = str(capability_filter_arg).lower()
        assert "capability" in rendered
        assert " in " in rendered


@pytest.mark.asyncio
class TestDegradation:
    async def test_mark_degraded_records_failure(self, db):
        router = LLMRouter(db)
        provider_id = str(uuid4())

        with patch("services.llm_router.get_degradation_tracker") as mock_tracker:
            await router._mark_degraded(provider_id, "provider-name", "LLMTimeoutError", "timeout")
            mock_tracker.return_value.record.assert_called_once()

    async def test_mark_success_clears_failure(self, db):
        router = LLMRouter(db)
        provider_id = str(uuid4())
        router._failure_counts[provider_id] = 2
        router._degraded_until[provider_id] = MagicMock()

        await router._mark_success(provider_id)

        assert provider_id not in router._failure_counts
        assert provider_id not in router._degraded_until
