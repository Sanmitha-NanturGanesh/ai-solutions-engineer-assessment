from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .rate_limiter import SQLiteTokenRateLimiter

app = FastAPI(title="Resilient LLM Router")

PRIMARY_URL = os.getenv("PRIMARY_MODEL_URL", "http://127.0.0.1:9003/v1/completions")
SECONDARY_URL = os.getenv("SECONDARY_MODEL_URL", "http://127.0.0.1:9004/v1/completions")
DB_PATH = os.getenv("RATE_LIMIT_DB", "./rate_limit.sqlite3")
TOKEN_LIMIT = int(os.getenv("TOKENS_PER_MINUTE", "50000"))
TIMEOUT_SECONDS = int(os.getenv("UPSTREAM_TIMEOUT_MS", "3000")) / 1000

limiter = SQLiteTokenRateLimiter(DB_PATH, limit=TOKEN_LIMIT, window_seconds=60)


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=256, ge=1, le=8192)


def estimate_tokens(prompt: str, max_tokens: int) -> int:
    # For admission I reserve prompt + requested completion tokens. A production
    # gateway can reconcile this reservation with provider-reported usage later.
    prompt_tokens = max(1, (len(prompt) + 3) // 4)
    return prompt_tokens + max_tokens


def error_response(code: str, message: str, status_code: int, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        status_code=status_code,
    )


async def call_model(url: str, payload: dict[str, Any]) -> httpx.Response:
    timeout = httpx.Timeout(TIMEOUT_SECONDS, connect=TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(url, json=payload)


def successful_body(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@app.post("/v1/completions")
async def completions(request: Request, x_tenant_api_key: str | None = Header(default=None)) -> JSONResponse:
    if not x_tenant_api_key:
        return error_response("AUTH_REQUIRED", "Missing tenant API key", 401)

    try:
        raw = await request.json()
        parsed = CompletionRequest.model_validate(raw)
    except (ValueError, ValidationError):
        return error_response("INVALID_REQUEST", "Invalid completion request", 400)

    requested_tokens = estimate_tokens(parsed.prompt, parsed.max_tokens)
    allowed, remaining = await limiter.allow(x_tenant_api_key, requested_tokens)
    if not allowed:
        response = error_response("RATE_LIMITED", "Tenant token budget exceeded", 429, retryable=True)
        response.headers["X-RateLimit-Limit-Tokens"] = str(TOKEN_LIMIT)
        response.headers["X-RateLimit-Remaining-Tokens"] = str(remaining)
        return response

    fallback_reason: str | None = None
    try:
        primary = await call_model(PRIMARY_URL, raw)
        if primary.status_code == 429:
            fallback_reason = "primary_rate_limited"
        elif primary.is_success:
            body = successful_body(primary)
            if body is None:
                return error_response("UPSTREAM_ERROR", "Primary model returned an invalid response", 502, retryable=True)
            body.setdefault("gateway", {})["provider"] = "primary"
            return JSONResponse(body)
        else:
            # The task only asks for fallback on 429 or timeout. Other upstream
            # failures are returned as a sanitized gateway error.
            return error_response("UPSTREAM_ERROR", "Primary model request failed", 502, retryable=True)
    except httpx.TimeoutException:
        fallback_reason = "primary_timeout"
    except httpx.RequestError:
        return error_response("UPSTREAM_UNAVAILABLE", "Primary model unavailable", 502, retryable=True)

    try:
        secondary = await call_model(SECONDARY_URL, raw)
    except httpx.TimeoutException:
        return error_response("FALLBACK_TIMEOUT", "Backup model timed out", 504, retryable=True)
    except httpx.RequestError:
        return error_response("FALLBACK_UNAVAILABLE", "Backup model unavailable", 502, retryable=True)

    if not secondary.is_success:
        return error_response("FALLBACK_FAILED", "Backup model request failed", 502, retryable=True)

    body = successful_body(secondary)
    if body is None:
        return error_response("FALLBACK_FAILED", "Backup model returned an invalid response", 502, retryable=True)

    body.setdefault("gateway", {}).update({"provider": "secondary", "fallback_reason": fallback_reason})
    return JSONResponse(body)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
