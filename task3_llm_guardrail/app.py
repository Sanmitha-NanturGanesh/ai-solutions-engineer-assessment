from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .redactor import StreamingRedactor

app = FastAPI(title="LLM Streaming Guardrail")
PROVIDER_URL = os.getenv("LLM_PROVIDER_URL", "http://127.0.0.1:9002/v1/stream")


def get_delta(event: dict[str, Any]) -> str:
    if isinstance(event.get("delta"), str):
        return event["delta"]

    try:
        content = event["choices"][0]["delta"].get("content")
        return content if isinstance(content, str) else ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def replace_delta(event: dict[str, Any], text: str) -> dict[str, Any]:
    """Keep the provider event shape when possible."""
    if isinstance(event.get("delta"), str):
        event["delta"] = text
        return event

    try:
        event["choices"][0]["delta"]["content"] = text
        return event
    except (KeyError, IndexError, TypeError):
        return {"delta": text}


async def guarded_stream(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    redactor = StreamingRedactor()
    last_event: dict[str, Any] = {"delta": ""}
    timeout = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", PROVIDER_URL, json=payload) as upstream:
            if not upstream.is_success:
                # The response has not started yet, so fail without exposing the
                # provider body or exception details.
                raise RuntimeError("provider request failed")

            async for line in upstream.aiter_lines():
                if not line.startswith("data:"):
                    continue

                raw = line[5:].strip()
                if raw == "[DONE]":
                    tail = redactor.flush()
                    if tail:
                        yield f"data: {json.dumps(replace_delta(last_event.copy(), tail))}\n\n".encode()
                    yield b"data: [DONE]\n\n"
                    return

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if not isinstance(event, dict):
                    continue

                last_event = event
                safe_text = redactor.feed(get_delta(event))
                if safe_text:
                    yield f"data: {json.dumps(replace_delta(event, safe_text))}\n\n".encode()

    tail = redactor.flush()
    if tail:
        yield f"data: {json.dumps(replace_delta(last_event.copy(), tail))}\n\n".encode()


@app.post("/v1/generate")
async def generate(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "Request body must be JSON"}}, 400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "Request body must be an object"}}, 400)

    return StreamingResponse(guarded_stream(payload), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
