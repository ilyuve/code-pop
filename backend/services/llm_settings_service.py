"""CRUD and testing service for LLM provider configuration."""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models import LlmProvider
from services.llm_client import LLMClient, encrypt_api_key
from services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


def list_providers(db: Session, capability: Optional[str] = None) -> List[LlmProvider]:
    q = db.query(LlmProvider)
    if capability:
        q = q.filter(LlmProvider.capability.in_([capability, "both"]))
    return q.order_by(LlmProvider.priority.asc()).all()


def get_provider(db: Session, provider_id: UUID) -> Optional[LlmProvider]:
    return db.query(LlmProvider).filter(LlmProvider.id == provider_id).first()


def create_provider(db: Session, data: Dict[str, Any]) -> LlmProvider:
    api_key = data.get("api_key", "")
    if api_key:
        api_key = encrypt_api_key(api_key)
    provider = LlmProvider(
        name=data.get("name", ""),
        base_url=data.get("base_url", ""),
        api_key=api_key,
        model=data.get("model", ""),
        capability=data.get("capability", "chat"),
        priority=data.get("priority", 0),
        enabled=1 if data.get("enabled", True) else 0,
        max_tokens=data.get("max_tokens", 4096),
        temperature=data.get("temperature", 0.1),
        timeout_seconds=data.get("timeout_seconds", 60),
        extra_headers=data.get("extra_headers"),
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(db: Session, provider_id: UUID, data: Dict[str, Any]) -> Optional[LlmProvider]:
    provider = get_provider(db, provider_id)
    if not provider:
        return None

    updatable = [
        "name", "base_url", "model", "capability", "priority", "max_tokens",
        "temperature", "timeout_seconds", "extra_headers",
    ]
    for field in updatable:
        if field in data:
            setattr(provider, field, data[field])

    if "enabled" in data:
        provider.enabled = 1 if data["enabled"] else 0

    if "api_key" in data and data["api_key"]:
        provider.api_key = encrypt_api_key(data["api_key"])

    db.commit()
    db.refresh(provider)
    return provider


def delete_provider(db: Session, provider_id: UUID) -> bool:
    provider = get_provider(db, provider_id)
    if not provider:
        return False
    db.delete(provider)
    db.commit()
    return True


def mask_api_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


def provider_to_dict(provider: LlmProvider, include_key: bool = False) -> Dict[str, Any]:
    return {
        "id": str(provider.id),
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key": provider.api_key if include_key else mask_api_key(provider.api_key),
        "model": provider.model,
        "capability": provider.capability,
        "priority": provider.priority,
        "enabled": bool(provider.enabled),
        "max_tokens": provider.max_tokens,
        "temperature": provider.temperature,
        "timeout_seconds": provider.timeout_seconds,
        "extra_headers": provider.extra_headers,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


async def test_provider(db: Session, provider_id: UUID) -> Dict[str, Any]:
    """Send a minimal request through the provider and report latency."""
    provider = get_provider(db, provider_id)
    if not provider:
        return {"ok": False, "error": "Provider not found"}

    client = LLMClient(provider)
    try:
        if provider.capability in ("chat", "both"):
            resp = await client.chat([{"role": "user", "content": "hi"}])
            return {
                "ok": True,
                "latency_ms": resp.latency_ms,
                "model": resp.model,
                "sample": resp.content[:100],
            }
        elif provider.capability in ("embed", "both"):
            resp = await client.embed(["hello"])
            return {
                "ok": True,
                "latency_ms": resp[0].index,
                "model": provider.model,
                "embedding_dim": len(resp[0].embedding) if resp else 0,
            }
        else:
            return {"ok": False, "error": "Unknown capability"}
    except Exception as e:
        logger.warning("Provider test failed for %s: %s", provider.name, e)
        return {"ok": False, "error": str(e)}


def get_usage_summary(db: Session, minutes: int = 60) -> Dict[str, Any]:
    """Return aggregated LLM usage statistics."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from models import LlmUsageLog

    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    rows = (
        db.query(
            LlmUsageLog.status,
            func.count().label("count"),
            func.coalesce(func.sum(LlmUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmUsageLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LlmUsageLog.latency_ms), 0).label("latency_ms"),
        )
        .filter(LlmUsageLog.created_at >= cutoff)
        .group_by(LlmUsageLog.status)
        .all()
    )
    summary = {
        "period_minutes": minutes,
        "total_calls": 0,
        "success_calls": 0,
        "error_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
    }
    for row in rows:
        summary["total_calls"] += row.count
        if row.status == "success":
            summary["success_calls"] += row.count
            summary["input_tokens"] += int(row.input_tokens)
            summary["output_tokens"] += int(row.output_tokens)
            summary["latency_ms"] += int(row.latency_ms)
        else:
            summary["error_calls"] += row.count
    return summary
