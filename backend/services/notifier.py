"""WebSocket connection manager for broadcasting indexing progress."""

import json
import logging
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSNotifier:
    """Manage active WebSocket connections and broadcast messages."""

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._repo_subscriptions: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket connected, total clients: %d", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        for subscribers in self._repo_subscriptions.values():
            if websocket in subscribers:
                subscribers.remove(websocket)
        logger.info("WebSocket disconnected, total clients: %d", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Broadcast a JSON message to all connected clients."""
        if not self._connections:
            return
        payload = json.dumps(message)
        disconnected: List[WebSocket] = []
        for conn in self._connections:
            try:
                await conn.send_text(payload)
            except Exception as exc:
                logger.warning("Failed to send WS message: %s", exc)
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def send_repo_update(self, repo_id: str, status: str, progress: float, error: str | None = None) -> None:
        await self.broadcast(
            {
                "type": "repo_update",
                "repo_id": repo_id,
                "status": status,
                "progress": round(progress, 2),
                "error": error,
            }
        )


notifier = WSNotifier()
