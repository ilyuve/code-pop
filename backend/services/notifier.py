"""WebSocket connection manager for broadcasting indexing progress."""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _json_default(obj):
    """Serialize datetime objects as ISO 8601 with explicit UTC offset."""
    if isinstance(obj, datetime):
        dt = obj.replace(tzinfo=timezone.utc) if obj.tzinfo is None else obj
        return dt.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


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
        payload = json.dumps(message, default=_json_default)
        disconnected: List[WebSocket] = []
        for conn in self._connections:
            try:
                await conn.send_text(payload)
            except Exception as exc:
                logger.warning("Failed to send WS message: %s", exc)
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def send_repo_update(
        self,
        repo_id: str,
        status: str,
        progress: float,
        error: Optional[str] = None,
        stage: Optional[str] = None,
        stage_progress: Optional[dict] = None,
        log_message: Optional[str] = None,
        log_level: str = "info",
        branch: str = "main",
        sync_result: Optional[dict] = None,
    ) -> None:
        payload: dict = {
            "type": "repo_update",
            "repoId": repo_id,
            "status": status,
            "progress": round(progress, 2),
            "stage": stage,
            "stage_progress": stage_progress,
            "error": error,
            "branch": branch,
        }

        if sync_result:
            payload["sync_result"] = sync_result

        if log_message:
            payload["log"] = {
                "message": log_message,
                "level": log_level,
                "timestamp": datetime.utcnow(),
            }

        await self.broadcast({k: v for k, v in payload.items() if v is not None})

    async def send_indexing_log(
        self,
        repo_id: str,
        logs: List[Dict[str, str]],
    ) -> None:
        payload: dict = {
            "type": "indexing_logs",
            "repoId": repo_id,
            "logs": logs,
        }
        await self.broadcast(payload)


notifier = WSNotifier()
