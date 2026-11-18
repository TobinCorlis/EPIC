import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.models.collaboration import DebateEvent


class DebateConnectionManager:
    def __init__(self):
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, debate_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections[debate_id].add(websocket)

    async def disconnect(self, debate_id: int, websocket: WebSocket):
        async with self._lock:
            self._connections[debate_id].discard(websocket)

    async def broadcast(self, debate_id: int, message: dict[str, Any]):
        stale = []
        for ws in list(self._connections.get(debate_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.disconnect(debate_id, ws)


manager = DebateConnectionManager()


def record_event(db: Session, debate_id: int, event_type: str, payload: dict, actor_user_id: int | None = None) -> DebateEvent:
    event = DebateEvent(
        debate_id=debate_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        payload_json=json.dumps(payload, default=str),
    )
    db.add(event)
    db.flush()
    return event


def event_dict(event: DebateEvent) -> dict:
    return {
        "id": event.id,
        "debate_id": event.debate_id,
        "event_type": event.event_type,
        "actor_user_id": event.actor_user_id,
        "payload": json.loads(event.payload_json or "{}"),
        "created_at": event.created_at.isoformat(),
    }
