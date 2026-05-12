from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.chat_orchestrator import run_chat

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.post("/chat")
async def chat(body: ChatRequest):
    return await run_chat(body.message)
