from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.state import session

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await session.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "plan_updated",
                "revision": session.revision,
                "plan": json.loads(session.plan.model_dump_json()),
            }
        )
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=120.0)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        session.disconnect(websocket)
