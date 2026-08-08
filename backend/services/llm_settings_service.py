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
        provider_type=data.get("provider_type", "openai_compatible"),
        base_url=data.get("base_url", ""),
        api_key=api_key,
        model=data.get("model", ""),
        capability=data.get("capability", "chat"),
        priority=data.get("priority", 0),
        enabled=1 if data.get("enabled", True) else 0,
        max_tokens=data.get("max_tokens", 4096),
        temperature=data.get("temperature", 0.1),
        timeout_seconds=data.get("timeout_seconds", 60),
        cost_per_1k_input=data.get("cost_per_1k_input", 0),
        cost_per_1k_output=data.get("cost_per_1k_output", 0),
        extra_headers=data.get("extra_headers"),
        extra_body=data.get("extra_body"),
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
        "name", "provider_type", "base_url", "model", "capability", "priority",
        "max_tokens", "temperature", "timeout_seconds", "extra_headers", "extra_body",
    ]
    for field in updatable:
        if field in data:
            setattr(provider, field, data[field])

    numeric_fields = ["cost_per_1k_input", "cost_per_1k_output"]
    for field in numeric_fields:
        if field in data and data[field] is not None:
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
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "api_key": provider.api_key if include_key else mask_api_key(provider.api_key),
        "model": provider.model,
        "capability": provider.capability,
        "priority": provider.priority,
        "enabled": bool(provider.enabled),
        "max_tokens": provider.max_tokens,
        "temperature": provider.temperature,
        "timeout_seconds": provider.timeout_seconds,
        "cost_per_1k_input": float(provider.cost_per_1k_input) if provider.cost_per_1k_input is not None else 0.0,
        "cost_per_1k_output": float(provider.cost_per_1k_output) if provider.cost_per_1k_output is not None else 0.0,
        "extra_headers": provider.extra_headers,
        "extra_body": provider.extra_body,
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


def get_usage_summary(
    db: Session, minutes: int = 60, days: Optional[int] = None
) -> Dict[str, Any]:
    """Return aggregated LLM usage statistics.

    When ``days`` is provided it takes precedence over ``minutes``.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from models import LlmUsageLog

    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        period_label = {"period_days": days}
    else:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        period_label = {"period_minutes": minutes}

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
        **period_label,
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


def _safe_decimal(value: Any) -> float:
    """Convert a numeric value to float, defaulting to 0 on None/invalid."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _calculate_token_cost(
    input_tokens: int,
    output_tokens: int,
    cost_per_1k_input: float,
    cost_per_1k_output: float,
) -> float:
    """Compute USD cost from token counts and per-1k rates."""
    input_cost = (input_tokens / 1000.0) * cost_per_1k_input
    output_cost = (output_tokens / 1000.0) * cost_per_1k_output
    return round(input_cost + output_cost, 6)


def get_cost_estimate(
    db: Session, minutes: int = 60, days: Optional[int] = None, repo_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """Return estimated LLM cost based on usage logs and provider rates.

    Aggregates successful usage logs within the period, joins provider rates,
    and returns total cost plus per-provider and per-operation breakdowns.
    When ``days`` is provided it takes precedence over ``minutes``.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from models import LlmProvider, LlmUsageLog

    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        period_label = {"period_days": days}
    else:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        period_label = {"period_minutes": minutes}

    query = (
        db.query(
            LlmUsageLog.provider_id,
            LlmUsageLog.operation,
            LlmProvider.name.label("provider_name"),
            LlmProvider.cost_per_1k_input,
            LlmProvider.cost_per_1k_output,
            func.count().label("call_count"),
            func.coalesce(func.sum(LlmUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .outerjoin(LlmProvider, LlmUsageLog.provider_id == LlmProvider.id)
        .filter(LlmUsageLog.created_at >= cutoff)
        .filter(LlmUsageLog.status == "success")
    )
    if repo_id:
        query = query.filter(LlmUsageLog.repo_id == repo_id)
    rows = query.group_by(
        LlmUsageLog.provider_id,
        LlmUsageLog.operation,
        LlmProvider.name,
        LlmProvider.cost_per_1k_input,
        LlmProvider.cost_per_1k_output,
    ).all()

    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    provider_breakdown: Dict[str, Dict[str, Any]] = {}
    operation_breakdown: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        input_tokens = int(row.input_tokens)
        output_tokens = int(row.output_tokens)
        cost_per_1k_input = _safe_decimal(row.cost_per_1k_input)
        cost_per_1k_output = _safe_decimal(row.cost_per_1k_output)
        cost = _calculate_token_cost(
            input_tokens, output_tokens, cost_per_1k_input, cost_per_1k_output
        )

        total_cost += cost
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

        provider_name = row.provider_name or "unknown"
        if provider_name not in provider_breakdown:
            provider_breakdown[provider_name] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "call_count": 0,
                "cost": 0.0,
            }
        provider_breakdown[provider_name]["input_tokens"] += input_tokens
        provider_breakdown[provider_name]["output_tokens"] += output_tokens
        provider_breakdown[provider_name]["call_count"] += int(row.call_count)
        provider_breakdown[provider_name]["cost"] = round(
            provider_breakdown[provider_name]["cost"] + cost, 6
        )

        operation = row.operation or "unknown"
        if operation not in operation_breakdown:
            operation_breakdown[operation] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "call_count": 0,
                "cost": 0.0,
            }
        operation_breakdown[operation]["input_tokens"] += input_tokens
        operation_breakdown[operation]["output_tokens"] += output_tokens
        operation_breakdown[operation]["call_count"] += int(row.call_count)
        operation_breakdown[operation]["cost"] = round(
            operation_breakdown[operation]["cost"] + cost, 6
        )

    return {
        **period_label,
        "repo_id": str(repo_id) if repo_id else None,
        "total_cost": round(total_cost, 6),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "provider_breakdown": provider_breakdown,
        "operation_breakdown": operation_breakdown,
    }


def get_daily_usage(
    db: Session, days: int = 7, repo_id: Optional[UUID] = None
) -> List[Dict[str, Any]]:
    """Return daily LLM usage aggregates for charting.

    Returns one row per day with total calls, input/output tokens and
    estimated cost. Days with no usage are not included.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func, cast, Date
    from models import LlmProvider, LlmUsageLog

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = (
        db.query(
            cast(LlmUsageLog.created_at, Date).label("date"),
            func.count().label("call_count"),
            func.coalesce(func.sum(LlmUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmUsageLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LlmUsageLog.latency_ms), 0).label("latency_ms"),
            LlmProvider.cost_per_1k_input,
            LlmProvider.cost_per_1k_output,
        )
        .outerjoin(LlmProvider, LlmUsageLog.provider_id == LlmProvider.id)
        .filter(LlmUsageLog.created_at >= cutoff)
        .filter(LlmUsageLog.status == "success")
    )
    if repo_id:
        query = query.filter(LlmUsageLog.repo_id == repo_id)
    rows = (
        query.group_by(
            cast(LlmUsageLog.created_at, Date),
            LlmProvider.cost_per_1k_input,
            LlmProvider.cost_per_1k_output,
        )
        .order_by("date")
        .all()
    )

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        date_str = str(row.date)
        entry = result.setdefault(
            date_str,
            {
                "date": date_str,
                "call_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "cost": 0.0,
            },
        )
        input_tokens = int(row.input_tokens)
        output_tokens = int(row.output_tokens)
        cost_per_1k_input = _safe_decimal(row.cost_per_1k_input)
        cost_per_1k_output = _safe_decimal(row.cost_per_1k_output)
        cost = _calculate_token_cost(
            input_tokens, output_tokens, cost_per_1k_input, cost_per_1k_output
        )
        entry["call_count"] += int(row.call_count)
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["latency_ms"] += int(row.latency_ms)
        entry["cost"] = round(entry["cost"] + cost, 6)
    return list(result.values())


# ---------------------------------------------------------------------------
# LLM feature toggles (global / per-repo)
# ---------------------------------------------------------------------------

from models import LlmSetting  # noqa: E402


def _settings_to_dict(row: LlmSetting) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "repo_id": str(row.repo_id) if row.repo_id else None,
        "enable_index_chinese_enrich": bool(row.enable_index_chinese_enrich),
        "enable_query_llm_expand": bool(row.enable_query_llm_expand),
        "enable_flow_label": bool(row.enable_flow_label),
        "default_provider_id": str(row.default_provider_id) if row.default_provider_id else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get_or_create_setting(
    db: Session, scope: str, repo_id: Optional[UUID] = None
) -> LlmSetting:
    query = db.query(LlmSetting).filter(LlmSetting.scope == scope)
    if repo_id:
        query = query.filter(LlmSetting.repo_id == repo_id)
    else:
        query = query.filter(LlmSetting.repo_id.is_(None))
    row = query.first()
    if row is None:
        row = LlmSetting(scope=scope, repo_id=repo_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_global_settings(db: Session) -> Dict[str, Any]:
    return _settings_to_dict(_get_or_create_setting(db, "global"))


def update_global_settings(db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
    row = _get_or_create_setting(db, "global")
    _apply_setting_fields(row, data)
    db.commit()
    db.refresh(row)
    return _settings_to_dict(row)


def get_repo_settings(db: Session, repo_id: UUID) -> Dict[str, Any]:
    return _settings_to_dict(_get_or_create_setting(db, "repo", repo_id))


def update_repo_settings(
    db: Session, repo_id: UUID, data: Dict[str, Any]
) -> Dict[str, Any]:
    row = _get_or_create_setting(db, "repo", repo_id)
    _apply_setting_fields(row, data)
    db.commit()
    db.refresh(row)
    return _settings_to_dict(row)


def _apply_setting_fields(row: LlmSetting, data: Dict[str, Any]) -> None:
    bool_fields = [
        "enable_index_chinese_enrich",
        "enable_query_llm_expand",
        "enable_flow_label",
    ]
    for field in bool_fields:
        if field in data:
            setattr(row, field, 1 if data[field] else 0)

    if "default_provider_id" in data:
        raw = data["default_provider_id"]
        row.default_provider_id = UUID(raw) if raw else None


def get_effective_settings(
    db: Session, repo_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """Return merged settings: repo overrides global, missing values fall back to global."""
    global_row = _get_or_create_setting(db, "global")
    effective = _settings_to_dict(global_row)

    if repo_id:
        repo_row = _get_or_create_setting(db, "repo", repo_id)
        repo_dict = _settings_to_dict(repo_row)
        # Repo overrides only when explicitly set; here stored row already carries value.
        for key in ["enable_index_chinese_enrich", "enable_query_llm_expand", "enable_flow_label", "default_provider_id"]:
            effective[key] = repo_dict[key]

    return effective
