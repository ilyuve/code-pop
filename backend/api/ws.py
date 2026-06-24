"""WebSocket endpoint for indexing progress notifications."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.notifier import notifier

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await notifier.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                data = {"raw": message}
            # Simple ping/pong heartbeat.
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        notifier.disconnect(websocket)
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
        notifier.disconnect(websocket)
