"""Tests for the OpenAI-compatible LLM client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.llm_client import (
    LLMChatResponse,
    LLMClient,
    LLMFormatError,
    LLMProviderError,
    LLMTimeoutError,
    decrypt_api_key,
    encrypt_api_key,
)


def test_encryption_roundtrip():
    key = "sk-test-secret-key"
    encrypted = encrypt_api_key(key)
    assert encrypted != key
    assert decrypt_api_key(encrypted) == key


def test_encryption_is_deterministic_with_same_secret():
    key = "sk-test"
    assert decrypt_api_key(encrypt_api_key(key)) == key


@pytest.fixture
def provider():
    p = MagicMock()
    p.api_key = encrypt_api_key("sk-test")
    p.base_url = "https://api.example.com"
    p.model = "test-model"
    p.timeout_seconds = 30
    p.max_tokens = 1024
    p.temperature = 0.1
    p.extra_headers = None
    p.name = "test-provider"
    return p


@pytest.mark.asyncio
class TestChat:
    async def test_chat_returns_parsed_response(self, provider):
        client = LLMClient(provider)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "content": "hello world",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await client.chat([{"role": "user", "content": "hi"}])

        assert isinstance(resp, LLMChatResponse)
        assert resp.content == "hello world"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5
        assert resp.model == "test-model"
        assert resp.latency_ms >= 0

    async def test_chat_raises_on_timeout(self, provider):
        client = LLMClient(provider)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMTimeoutError):
                await client.chat([{"role": "user", "content": "hi"}])

    async def test_chat_raises_on_auth_error(self, provider):
        client = LLMClient(provider)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMProviderError):
                await client.chat([{"role": "user", "content": "hi"}])

    async def test_chat_raises_format_error_on_empty_content(self, provider):
        client = LLMClient(provider)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}],
            "usage": {},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(LLMFormatError):
                await client.chat([{"role": "user", "content": "hi"}])

    async def test_chat_sends_response_format(self, provider):
        client = LLMClient(provider)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await client.chat(
                [{"role": "user", "content": "hi"}],
                response_format={"type": "json_object"},
            )

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
class TestEmbed:
    async def test_embed_returns_vectors(self, provider):
        client = LLMClient(provider)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await client.embed(["hello", "world"])

        assert len(results) == 2
        assert results[0].embedding == [0.1, 0.2, 0.3]
        assert results[1].embedding == [0.4, 0.5, 0.6]
