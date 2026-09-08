from fastapi import FastAPI
app = FastAPI()
@app.post("/v1/completions")
async def complete():
    return {"id": "secondary-1", "text": "secondary response"}
