"""Tests for admin LLM provider API endpoints."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Patch DB initialization before importing the main app.
with patch("scripts.init_db.init_db"):
    from main import app
    from api.admin import llm as admin_llm


def _make_provider(name="test", capability="chat"):
    p = MagicMock()
    p.id = uuid4()
    p.name = name
    p.provider_type = "openai_compatible"
    p.base_url = "https://api.example.com"
    p.api_key = "encrypted"
    p.model = "model"
    p.capability = capability
    p.priority = 0
    p.enabled = 1
    p.max_tokens = 1024
    p.temperature = 0.1
    p.timeout_seconds = 30
    p.cost_per_1k_input = 0.001
    p.cost_per_1k_output = 0.002
    p.extra_headers = None
    p.extra_body = None
    p.created_at = None
    p.updated_at = None
    return p


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db():
    db = MagicMock()
    app.dependency_overrides[admin_llm.get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


def test_list_providers(client, mock_db):
    # list_providers without capability does not apply a capability filter,
    # so the mock chain is query(...).order_by(...).all().
    mock_db.query.return_value.order_by.return_value.all.return_value = [
        _make_provider("primary")
    ]

    resp = client.get("/api/admin/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["providers"]) == 1
    assert data["providers"][0]["name"] == "primary"


def test_create_provider(client, mock_db):
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    provider = _make_provider("new")

    with patch("api.admin.llm.create_provider", return_value=provider) as mock_create:
        resp = client.post(
            "/api/admin/llm/providers",
            json={
                "name": "new",
                "base_url": "https://api.example.com",
                "api_key": "sk-secret",
                "model": "model",
            },
        )

    assert resp.status_code == 200
    mock_create.assert_called_once()
    assert resp.json()["provider"]["name"] == "new"


def test_get_provider(client, mock_db):
    provider_id = uuid4()
    mock_db.query.return_value.filter.return_value.first.return_value = _make_provider("primary")

    resp = client.get(f"/api/admin/llm/providers/{provider_id}")
    assert resp.status_code == 200
    assert resp.json()["provider"]["name"] == "primary"


def test_get_provider_not_found(client, mock_db):
    provider_id = uuid4()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.get(f"/api/admin/llm/providers/{provider_id}")
    assert resp.status_code == 404


def test_update_provider(client, mock_db):
    provider_id = uuid4()
    provider = _make_provider("updated")
    mock_db.query.return_value.filter.return_value.first.return_value = provider

    resp = client.put(
        f"/api/admin/llm/providers/{provider_id}",
        json={"name": "updated"},
    )
    assert resp.status_code == 200


def test_delete_provider(client, mock_db):
    provider_id = uuid4()
    mock_db.query.return_value.filter.return_value.first.return_value = _make_provider()

    resp = client.delete(f"/api/admin/llm/providers/{provider_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_delete_provider_not_found(client, mock_db):
    provider_id = uuid4()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.delete(f"/api/admin/llm/providers/{provider_id}")
    assert resp.status_code == 404


def test_usage_summary(client, mock_db):
    mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = []

    resp = client.get("/api/admin/llm/usage?minutes=60")
    assert resp.status_code == 200
    assert resp.json()["period_minutes"] == 60


def test_cost_estimate(client, mock_db):
    mock_db.query.return_value.outerjoin.return_value.filter.return_value.filter.return_value.group_by.return_value.all.return_value = []

    resp = client.get("/api/admin/llm/cost?minutes=60")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_minutes"] == 60
    assert data["total_cost"] == 0
    assert data["provider_breakdown"] == {}
