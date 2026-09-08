import asyncio
import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

async def stream():
    chunks = [
        "Contact jane.d", "oe@example.com or SSN 123-", "45-6789. Card 4242 4242 ", "4242 4242. Done."
    ]
    for chunk in chunks:
        await asyncio.sleep(0.03)
        yield f"data: {json.dumps({'delta': chunk})}\n\n"
    yield "data: [DONE]\n\n"

@app.post("/v1/stream")
async def generate():
    return StreamingResponse(stream(), media_type="text/event-stream")
