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
    get_provider,
    get_usage_summary,
    list_providers,
    provider_to_dict,
    test_provider,
    update_provider,
)

router = APIRouter(prefix="/api/admin/llm", tags=["admin-llm"])


class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    capability: str = Field(default="chat")
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.1)
    timeout_seconds: int = Field(default=60)
    extra_headers: Optional[str] = None


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    capability: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout_seconds: Optional[int] = None
    extra_headers: Optional[str] = None


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
def usage_summary(minutes: int = 60, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return get_usage_summary(db, minutes=minutes)
