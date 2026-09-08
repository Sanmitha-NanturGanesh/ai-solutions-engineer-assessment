from fastapi import FastAPI, Request

app = FastAPI()

TOOLS = [
    {"name": "get_customer_record", "description": "Read customer"},
    {"name": "admin_reset_key", "description": "Administrative key reset"},
]

@app.post("/rpc")
async def rpc(request: Request):
    body = await request.json()
    method = body.get("method")
    rid = body.get("id")
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (body.get("params") or {}).get("name")
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": f"executed:{name}"}]}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
