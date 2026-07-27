"""Tests for LLM provider settings CRUD and testing service."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.llm_settings_service import (
    create_provider,
    delete_provider,
    get_provider,
    get_usage_summary,
    list_providers,
    mask_api_key,
    provider_to_dict,
    update_provider,
)


def test_mask_api_key_short():
    assert mask_api_key("abc") == "***"


def test_mask_api_key_long():
    masked = mask_api_key("sk-1234567890abcdef")
    assert masked.startswith("sk-1")
    assert masked.endswith("cdef")
    assert "..." in masked


def test_provider_to_dict_masks_key():
    p = MagicMock()
    p.id = uuid4()
    p.name = "test"
    p.base_url = "https://api.example.com"
    p.api_key = "sk-secret"
    p.model = "model"
    p.capability = "chat"
    p.priority = 0
    p.enabled = 1
    p.max_tokens = 1024
    p.temperature = 0.1
    p.timeout_seconds = 30
    p.extra_headers = None
    p.created_at = None
    p.updated_at = None

    d = provider_to_dict(p)
    assert d["api_key"] != "sk-secret"
    assert "..." in d["api_key"]


def test_provider_to_dict_can_include_key():
    p = MagicMock()
    p.api_key = "sk-secret"
    d = provider_to_dict(p, include_key=True)
    assert d["api_key"] == "sk-secret"


def test_list_providers_filters_by_capability():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    result = list_providers(db, capability="chat")
    assert result == []
    db.query.assert_called_once()


def test_create_provider_encrypts_api_key():
    db = MagicMock()
    data = {
        "name": "test",
        "base_url": "https://api.example.com",
        "api_key": "sk-secret",
        "model": "model",
    }
    provider = create_provider(db, data)
    assert provider.api_key != "sk-secret"
    db.add.assert_called_once_with(provider)
    db.commit.assert_called_once()


def test_update_provider_leaves_key_unchanged_when_empty():
    db = MagicMock()
    provider_id = uuid4()
    existing = MagicMock()
    existing.api_key = "existing-encrypted"
    db.query.return_value.filter.return_value.first.return_value = existing

    update_provider(db, provider_id, {"name": "new name"})
    assert existing.name == "new name"
    assert existing.api_key == "existing-encrypted"


def test_update_provider_encrypts_new_key():
    db = MagicMock()
    provider_id = uuid4()
    existing = MagicMock()
    existing.api_key = "existing-encrypted"
    db.query.return_value.filter.return_value.first.return_value = existing

    update_provider(db, provider_id, {"api_key": "sk-new"})
    assert existing.api_key != "sk-new"
    assert existing.api_key != "existing-encrypted"


def test_delete_provider():
    db = MagicMock()
    provider_id = uuid4()
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    assert delete_provider(db, provider_id) is True
    db.delete.assert_called_once_with(existing)
    db.commit.assert_called_once()


def test_delete_provider_not_found():
    db = MagicMock()
    provider_id = uuid4()
    db.query.return_value.filter.return_value.first.return_value = None

    assert delete_provider(db, provider_id) is False


@pytest.mark.asyncio
class TestProvider:
    async def test_test_provider_chat(self):
        db = MagicMock()
        provider_id = uuid4()
        provider = MagicMock()
        provider.capability = "chat"
        db.query.return_value.filter.return_value.first.return_value = provider

        from services.llm_settings_service import test_provider

        with patch("services.llm_settings_service.LLMClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat = AsyncMock(
                return_value=MagicMock(
                    content="hi there",
                    latency_ms=42,
                    model="model",
                )
            )
            mock_client_cls.return_value = mock_client

            result = await test_provider(db, provider_id)

        assert result["ok"] is True
        assert result["latency_ms"] == 42

    async def test_test_provider_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        from services.llm_settings_service import test_provider

        result = await test_provider(db, uuid4())
        assert result["ok"] is False
        assert "not found" in result["error"].lower()


def test_get_usage_summary():
    db = MagicMock()
    row = MagicMock()
    row.status = "success"
    row.count = 5
    row.input_tokens = 100
    row.output_tokens = 50
    row.latency_ms = 500
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [row]

    summary = get_usage_summary(db, minutes=60)
    assert summary["total_calls"] == 5
    assert summary["success_calls"] == 5
    assert summary["input_tokens"] == 100
