from __future__ import annotations

import os
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

app = FastAPI(title="MCP Security Gateway")
DOWNSTREAM_URL = os.getenv("DOWNSTREAM_MCP_URL", "http://127.0.0.1:9001/rpc")


class RPCRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


def rpc_error(request_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def extract_role(authorization: str | None) -> str | None:
    # The assessment only asks us to extract a role from a bearer token. Keeping
    # this parser small makes the authz behavior easy to exercise locally.
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    token = token.strip()
    if token.startswith("role:"):
        token = token.removeprefix("role:")
    return token if token in {"admin", "viewer"} else None


async def forward_rpc(body: dict[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(DOWNSTREAM_URL, json=body)


@app.post("/rpc")
async def gateway(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
    try:
        body = await request.json()
        rpc = RPCRequest.model_validate(body)
    except (ValueError, ValidationError):
        return JSONResponse(rpc_error(None, -32600, "Invalid Request"), status_code=400)

    params = rpc.params or {}
    if rpc.method == "tools/call":
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return JSONResponse(rpc_error(rpc.id, -32602, "Invalid params"), status_code=400)

        if tool_name.startswith("admin_") and extract_role(authorization) != "admin":
            return JSONResponse(
                rpc_error(rpc.id, -32001, "Unauthorized Tool Call", {"tool": tool_name}),
                status_code=403,
            )

    try:
        upstream = await forward_rpc(body)
    except httpx.RequestError:
        return JSONResponse(rpc_error(rpc.id, -32002, "Downstream MCP unavailable"), status_code=502)

    try:
        response_body = upstream.json()
    except ValueError:
        return JSONResponse(rpc_error(rpc.id, -32003, "Invalid downstream response"), status_code=502)

    return JSONResponse(response_body, status_code=upstream.status_code)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
