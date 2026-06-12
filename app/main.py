"""FastAPI app: chat endpoint + static frontend.

Run locally:  uvicorn app.main:app --reload
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent import run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = FastAPI(title="nba-viz")
STATIC = Path(__file__).parent / "static"


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = []


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = run_agent(req.message, [t.model_dump() for t in req.history])
        return result
    except Exception as e:  # surface a friendly error, log the real one
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
