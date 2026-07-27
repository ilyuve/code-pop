"""Multi-provider LLM router with automatic fallback and degradation tracking."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from database import SessionLocal
from models import LlmProvider, LlmUsageLog
from services.degradation_tracker import get_degradation_tracker
from services.llm_client import (
    LLMChatResponse,
    LLMEmbeddingResponse,
    LLMClient,
    LLMError,
    LLMTimeoutError,
    LLMProviderError,
    LLMFormatError,
)

logger = logging.getLogger(__name__)


class LLMUnavailableError(LLMError):
    pass


class LLMRouter:
    """Route LLM calls across configured providers, falling back on failure."""

    _degraded_until: Dict[str, datetime] = {}
    _failure_counts: Dict[str, int] = {}
    _lock = asyncio.Lock()

    def __init__(self, db: Optional[Session] = None):
        self.db = db or SessionLocal()

    def _get_enabled_providers(self, capability: str) -> List[LlmProvider]:
        """Return enabled providers matching the requested capability, sorted by priority."""
        query = self.db.query(LlmProvider).filter(LlmProvider.enabled == 1)
        if capability == "chat":
            query = query.filter(LlmProvider.capability.in_(["chat", "both"]))
        elif capability == "embed":
            query = query.filter(LlmProvider.capability.in_(["embed", "both"]))
        providers = query.order_by(LlmProvider.priority.asc()).all()
        now = datetime.utcnow()
        available = []
        for p in providers:
            until = LLMRouter._degraded_until.get(str(p.id))
            if until and now < until:
                logger.info("Provider %s is degraded until %s", p.name, until.isoformat())
                continue
            available.append(p)
        return available

    async def _mark_degraded(self, provider_id: str, provider_name: str, error_type: str, message: str):
        async with LLMRouter._lock:
            count = LLMRouter._failure_counts.get(provider_id, 0) + 1
            LLMRouter._failure_counts[provider_id] = count
            backoff_minutes = {1: 1, 2: 5}.get(count, 30)
            until = datetime.utcnow() + timedelta(minutes=backoff_minutes)
            LLMRouter._degraded_until[provider_id] = until

        get_degradation_tracker().record(
            component=f"llm:{provider_name}",
            error_type=error_type,
            error_message=message[:200],
            fallback_action="switch_to_next_provider",
        )
        logger.warning("Provider %s marked degraded until %s", provider_name, until.isoformat())

    async def _mark_success(self, provider_id: str):
        async with LLMRouter._lock:
            LLMRouter._failure_counts.pop(provider_id, None)
            LLMRouter._degraded_until.pop(provider_id, None)

    def _write_usage_log(
        self,
        provider_id: Optional[str],
        repo_id: Optional[str],
        operation: str,
        status: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error_message: Optional[str] = None,
    ):
        try:
            log = LlmUsageLog(
                provider_id=provider_id,
                repo_id=repo_id,
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.error("Failed to write LLM usage log: %s", e)
            self.db.rollback()

    async def _try_provider_chat(
        self,
        provider: LlmProvider,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, str]],
        operation: str,
        repo_id: Optional[str],
    ) -> Tuple[LLMChatResponse, str]:
        client = LLMClient(provider)
        start = __import__("time").time()
        try:
            resp = await client.chat(messages, response_format=response_format)
            latency_ms = resp.latency_ms
            await self._mark_success(str(provider.id))
            await asyncio.to_thread(
                self._write_usage_log,
                provider.id,
                repo_id,
                operation,
                "success",
                resp.input_tokens,
                resp.output_tokens,
                latency_ms,
                None,
            )
            return resp, str(provider.id)
        except (LLMTimeoutError, LLMProviderError, LLMFormatError) as e:
            latency_ms = int((__import__("time").time() - start) * 1000)
            error_type = type(e).__name__
            await self._mark_degraded(str(provider.id), provider.name, error_type, str(e))
            await asyncio.to_thread(
                self._write_usage_log,
                provider.id,
                repo_id,
                operation,
                "error",
                0,
                0,
                latency_ms,
                str(e)[:500],
            )
            raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        operation: str = "chat",
        repo_id: Optional[str] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Tuple[LLMChatResponse, str]:
        providers = self._get_enabled_providers("chat")
        if not providers:
            raise LLMUnavailableError("No enabled LLM providers available")

        last_error: Optional[Exception] = None
        for provider in providers:
            try:
                resp, provider_id = await self._try_provider_chat(
                    provider, messages, response_format, operation, repo_id
                )
                return resp, provider_id
            except LLMError as e:
                last_error = e
                logger.warning("Provider %s failed for %s: %s", provider.name, operation, e)
                continue

        raise LLMUnavailableError(f"All LLM providers failed. Last error: {last_error}")

    async def embed(
        self,
        texts: List[str],
        operation: str = "embed",
        repo_id: Optional[str] = None,
    ) -> Tuple[List[LLMEmbeddingResponse], str]:
        providers = self._get_enabled_providers("embed")
        if not providers:
            raise LLMUnavailableError("No enabled embedding providers available")

        last_error: Optional[Exception] = None
        for provider in providers:
            client = LLMClient(provider)
            try:
                start = __import__("time").time()
                resp = await client.embed(texts)
                latency_ms = int((__import__("time").time() - start) * 1000)
                await self._mark_success(str(provider.id))
                await asyncio.to_thread(
                    self._write_usage_log,
                    provider.id,
                    repo_id,
                    operation,
                    "success",
                    0,
                    0,
                    latency_ms,
                    None,
                )
                return resp, str(provider.id)
            except LLMError as e:
                await self._mark_degraded(str(provider.id), provider.name, type(e).__name__, str(e))
                last_error = e
                logger.warning("Embedding provider %s failed: %s", provider.name, e)
                continue

        raise LLMUnavailableError(f"All embedding providers failed. Last error: {last_error}")
