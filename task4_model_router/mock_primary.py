import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()


@app.post("/v1/completions")
async def complete(request: Request):
    body = await request.json()
    mode = body.get("mock_mode")

    if mode == "429":
        return JSONResponse({"error": "rate limited"}, status_code=429)
    if mode == "timeout":
        await asyncio.sleep(5)

    return {"id": "primary-1", "text": "primary response"}
