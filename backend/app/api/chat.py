from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.state import session
from app.services.chat_orchestrator import run_chat

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.post("/chat")
async def chat(body: ChatRequest):
    return await run_chat(body.message)


@router.post("/undo")
async def undo_last_chat():
    async with session.lock:
        prev = session.pop_undo()
        if prev is None:
            raise HTTPException(409, detail={"error": "nothing_to_undo"})
        session.set_plan(prev)
    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}
