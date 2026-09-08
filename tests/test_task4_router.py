from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport

import task4_model_router.app as router


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(router.limiter, "allow", AsyncMock(return_value=(True, 49_000)))
    transport = ASGITransport(app=router.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_primary_success_does_not_fallback(client, monkeypatch):
    call = AsyncMock(return_value=httpx.Response(200, json={"id": "p1", "text": "ok"}))
    monkeypatch.setattr(router, "call_model", call)

    response = await client.post(
        "/v1/completions",
        headers={"X-Tenant-API-Key": "tenant-a"},
        json={"prompt": "hello", "max_tokens": 20},
    )

    assert response.status_code == 200
    assert response.json()["gateway"]["provider"] == "primary"
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_429_falls_back_to_secondary(client, monkeypatch):
    call = AsyncMock(
        side_effect=[
            httpx.Response(429, json={"error": "too many requests"}),
            httpx.Response(200, json={"id": "s1", "text": "backup"}),
        ]
    )
    monkeypatch.setattr(router, "call_model", call)

    response = await client.post(
        "/v1/completions",
        headers={"X-Tenant-API-Key": "tenant-a"},
        json={"prompt": "hello", "max_tokens": 20},
    )

    assert response.status_code == 200
    assert response.json()["gateway"] == {
        "provider": "secondary",
        "fallback_reason": "primary_rate_limited",
    }
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_timeout_falls_back_to_secondary(client, monkeypatch):
    call = AsyncMock(
        side_effect=[
            httpx.ReadTimeout("primary timed out"),
            httpx.Response(200, json={"id": "s1", "text": "backup"}),
        ]
    )
    monkeypatch.setattr(router, "call_model", call)

    response = await client.post(
        "/v1/completions",
        headers={"X-Tenant-API-Key": "tenant-a"},
        json={"prompt": "hello", "max_tokens": 20},
    )

    assert response.status_code == 200
    assert response.json()["gateway"]["fallback_reason"] == "primary_timeout"


@pytest.mark.asyncio
async def test_upstream_error_is_sanitized(client, monkeypatch):
    monkeypatch.setattr(
        router,
        "call_model",
        AsyncMock(side_effect=httpx.ConnectError("secret.internal:9443 connection refused")),
    )

    response = await client.post(
        "/v1/completions",
        headers={"X-Tenant-API-Key": "tenant-a"},
        json={"prompt": "hello", "max_tokens": 20},
    )

    body = response.text
    assert response.status_code == 502
    assert "secret.internal" not in body
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
