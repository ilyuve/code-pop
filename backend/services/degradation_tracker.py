"""Degradation tracking: record and query degradation events."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DegradationEvent:
    timestamp: datetime
    component: str
    error_type: str
    error_message: str
    fallback_action: str


class DegradationTracker:
    _instance: Optional["DegradationTracker"] = None
    _events: List[DegradationEvent] = []
    _max_events: int = 100

    def __new__(cls) -> "DegradationTracker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def record(
        self,
        component: str,
        error_type: str,
        error_message: str,
        fallback_action: str,
    ) -> None:
        event = DegradationEvent(
            timestamp=datetime.utcnow(),
            component=component,
            error_type=error_type,
            error_message=error_message[:200],
            fallback_action=fallback_action,
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

        logger.warning(
            "[DEGRADE] %s: %s - %s -> %s",
            component,
            error_type,
            error_message[:100],
            fallback_action,
        )

    def get_recent(self, limit: int = 20) -> List[Dict]:
        events = self._events[-limit:]
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "component": e.component,
                "error_type": e.error_type,
                "error_message": e.error_message,
                "fallback_action": e.fallback_action,
            }
            for e in reversed(events)
        ]

    def get_stats(self, minutes: int = 30) -> Dict[str, int]:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        recent = [e for e in self._events if e.timestamp >= cutoff]
        stats: Dict[str, int] = {}
        for e in recent:
            stats[e.component] = stats.get(e.component, 0) + 1
        return {"total": len(recent), **stats}


_tracker: Optional[DegradationTracker] = None


def get_degradation_tracker() -> DegradationTracker:
    global _tracker
    if _tracker is None:
        _tracker = DegradationTracker()
    return _tracker
