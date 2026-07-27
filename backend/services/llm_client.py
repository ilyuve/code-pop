"""OpenAI-compatible LLM client with encrypted API keys and structured output support."""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet

from config import settings

logger = logging.getLogger(__name__)

# Simple symmetric encryption for API keys at rest.
# In production this should be backed by a proper KMS; here we derive a key
# from a configurable secret so the field is not plaintext.
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        # Derive a 32-byte url-safe base64 key from the application secret.
        secret = getattr(settings, "app_secret", "codepop-default-secret-key")
        import base64
        import hashlib

        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_api_key(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


class LLMError(Exception):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMFormatError(LLMError):
    pass


@dataclass
class LLMChatResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int


@dataclass
class LLMEmbeddingResponse:
    embedding: List[float]
    index: int


class LLMClient:
    """Generic OpenAI-compatible client supporting chat, embeddings and JSON mode."""

    def __init__(self, provider):
        self.provider = provider
        self.api_key = decrypt_api_key(provider.api_key)
        self.base_url = provider.base_url.rstrip("/")
        self.model = provider.model
        self.timeout = provider.timeout_seconds or 60
        self.extra_headers = json.loads(provider.extra_headers) if provider.extra_headers else {}

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, str]] = None,
    ) -> LLMChatResponse:
        url = f"{self.base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.provider.max_tokens,
            "temperature": self.provider.temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        import asyncio
        import time

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"LLM request timed out after {self.timeout}s: {e}")
        except httpx.HTTPError as e:
            raise LLMProviderError(f"LLM HTTP error: {e}")

        latency_ms = int((time.time() - start) * 1000)

        if resp.status_code >= 500:
            raise LLMProviderError(f"LLM server error {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 401:
            raise LLMProviderError("LLM authentication failed: invalid API key")
        if resp.status_code == 429:
            raise LLMProviderError("LLM rate limit exceeded")
        if resp.status_code >= 400:
            raise LLMProviderError(f"LLM client error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise LLMFormatError(f"Invalid JSON from LLM: {e}")

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        usage = data.get("usage", {})
        model = data.get("model", self.model)

        if not content:
            raise LLMFormatError("LLM returned empty content")

        return LLMChatResponse(
            content=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=model,
            latency_ms=latency_ms,
        )

    async def embed(self, texts: List[str]) -> List[LLMEmbeddingResponse]:
        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }

        import time

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Embedding request timed out after {self.timeout}s: {e}")
        except httpx.HTTPError as e:
            raise LLMProviderError(f"Embedding HTTP error: {e}")

        latency_ms = int((time.time() - start) * 1000)

        if resp.status_code != 200:
            raise LLMProviderError(f"Embedding error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise LLMFormatError(f"Invalid JSON from embedding endpoint: {e}")

        results = []
        for item in data.get("data", []):
            idx = item.get("index", len(results))
            embedding = item.get("embedding", [])
            results.append(LLMEmbeddingResponse(embedding=embedding, index=idx))

        logger.debug("Embedded %d texts via %s in %dms", len(texts), self.provider.name, latency_ms)
        return results
