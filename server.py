from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from data_loader import load_data
from agent import PropertyAssistant

load_dotenv()

_data_store = None
_assistant: PropertyAssistant | None = None
_lock = threading.Lock()

_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _data_store, _assistant
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
    data_dir = Path(__file__).parent / "data"
    _data_store = load_data(data_dir)
    _assistant = PropertyAssistant(_data_store)
    yield


app = FastAPI(title="UrbanTrace AI", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def root():
    return _HTML


@app.post("/chat")
def chat(body: ChatRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    with _lock:
        try:
            response = _assistant.ask(body.message.strip())
            return {"response": response}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.post("/reset")
def reset():
    global _assistant
    with _lock:
        _assistant = PropertyAssistant(_data_store)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)