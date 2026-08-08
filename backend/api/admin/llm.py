"""Admin API for LLM provider management, testing and usage monitoring."""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.llm_settings_service import (
    create_provider,
    delete_provider,
    get_cost_estimate,
    get_daily_usage,
    get_global_settings,
    get_provider,
    get_repo_settings,
    get_usage_summary,
    list_providers,
    provider_to_dict,
    test_provider,
    update_global_settings,
    update_provider,
    update_repo_settings,
)

router = APIRouter(prefix="/api/admin/llm", tags=["admin-llm"])


class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    provider_type: str = Field(default="openai_compatible")
    base_url: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    capability: str = Field(default="chat")
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.1)
    timeout_seconds: int = Field(default=60)
    cost_per_1k_input: float = Field(default=0.0)
    cost_per_1k_output: float = Field(default=0.0)
    extra_headers: Optional[str] = None
    extra_body: Optional[str] = None


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    capability: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout_seconds: Optional[int] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    extra_headers: Optional[str] = None
    extra_body: Optional[str] = None


@router.get("/providers")
def get_providers(
    capability: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    providers = list_providers(db, capability=capability)
    return {"providers": [provider_to_dict(p) for p in providers]}


@router.post("/providers")
def post_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    provider = create_provider(db, payload.model_dump())
    return {"provider": provider_to_dict(provider)}


@router.get("/providers/{provider_id}")
def get_provider_detail(provider_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    provider = get_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return {"provider": provider_to_dict(provider)}


@router.put("/providers/{provider_id}")
def put_provider(
    provider_id: UUID,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    provider = update_provider(db, provider_id, payload.model_dump(exclude_unset=True))
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return {"provider": provider_to_dict(provider)}


@router.delete("/providers/{provider_id}")
def remove_provider(provider_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    ok = delete_provider(db, provider_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return {"success": True}


@router.post("/providers/{provider_id}/test")
async def provider_test(provider_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return await test_provider(db, provider_id)


@router.get("/usage")
def usage_summary(
    minutes: int = 60,
    days: Optional[int] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return get_usage_summary(db, minutes=minutes, days=days)


@router.get("/cost")
def cost_estimate(
    minutes: int = 60,
    days: Optional[int] = None,
    repo_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return get_cost_estimate(db, minutes=minutes, days=days, repo_id=repo_id)


@router.get("/daily")
def daily_usage(
    days: int = 7,
    repo_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return {"daily": get_daily_usage(db, days=days, repo_id=repo_id)}


class SettingsUpdate(BaseModel):
    enable_index_chinese_enrich: Optional[bool] = None
    enable_query_llm_expand: Optional[bool] = None
    enable_flow_label: Optional[bool] = None
    default_provider_id: Optional[str] = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"settings": get_global_settings(db)}


@router.put("/settings")
def put_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"settings": update_global_settings(db, payload.model_dump(exclude_unset=True))}


@router.get("/settings/repos/{repo_id}")
def get_repo_setting(repo_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"settings": get_repo_settings(db, repo_id)}


@router.put("/settings/repos/{repo_id}")
def put_repo_setting(
    repo_id: UUID,
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return {"settings": update_repo_settings(db, repo_id, payload.model_dump(exclude_unset=True))}
