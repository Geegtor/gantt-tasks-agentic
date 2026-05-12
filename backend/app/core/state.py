from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.core.models import ProjectPlan
from app.core.seed import seed_plan

# Each entry is one completed round-trip: {"user": str, "assistant": str}
ChatTurn = dict[str, str]
MAX_HISTORY = 8  # keep last 8 user/assistant pairs (~16 messages) before pruning


class SessionState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._plan: ProjectPlan = seed_plan()
        self._revision: int = 0  # bumps on every set_plan; clients ignore stale WS payloads
        self._chat_turns: int = 0
        self._history: list[ChatTurn] = []
        self._connections: set[WebSocket] = set()

    @property
    def plan(self) -> ProjectPlan:
        return self._plan

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def reset_demo(self) -> None:
        self._plan = seed_plan()
        self._revision = 0
        self._chat_turns = 0
        self._history = []

    def set_plan(self, plan: ProjectPlan) -> None:
        self._plan = plan
        self._revision += 1

    def incr_chat_turn(self) -> int:
        self._chat_turns += 1
        return self._chat_turns

    def chat_turns(self) -> int:
        return self._chat_turns

    def add_history_turn(self, user: str, assistant: str) -> None:
        self._history.append({"user": user, "assistant": assistant})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

    def get_history(self) -> list[ChatTurn]:
        return list(self._history)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast_plan(self) -> None:
        if not self._connections:
            return
        payload = {
            "type": "plan_updated",
            "revision": self._revision,
            "plan": json.loads(self._plan.model_dump_json()),
        }
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


# Single global session for demo (no auth)
session = SessionState()
