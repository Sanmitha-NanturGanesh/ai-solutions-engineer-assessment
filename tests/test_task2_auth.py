from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport

import task2_mcp_gateway.app as gateway_module


@pytest.mark.asyncio
async def test_viewer_cannot_call_admin_tool(monkeypatch):
    downstream = AsyncMock()
    monkeypatch.setattr(gateway_module, "forward_rpc", downstream)

    transport = ASGITransport(app=gateway_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/rpc",
            headers={"Authorization": "Bearer viewer"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "admin_reset_key", "arguments": {}},
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == -32001
    downstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_call_is_forwarded(monkeypatch):
    downstream = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
        )
    )
    monkeypatch.setattr(gateway_module, "forward_rpc", downstream)

    transport = ASGITransport(app=gateway_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/rpc",
            headers={"Authorization": "Bearer admin"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "admin_reset_key", "arguments": {}},
            },
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True}
    downstream.assert_awaited_once()


@pytest.mark.asyncio
async def test_tools_list_is_transparent(monkeypatch):
    expected = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"tools": [{"name": "admin_reset_key"}, {"name": "get_status"}]},
    }
    downstream = AsyncMock(return_value=httpx.Response(200, json=expected))
    monkeypatch.setattr(gateway_module, "forward_rpc", downstream)

    transport = ASGITransport(app=gateway_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/rpc",
            headers={"Authorization": "Bearer viewer"},
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )

    assert response.json() == expected
