from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable


class EventBus:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"type": event_type, "payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()}
        self.events.append(event)
        for handler in self._subscribers[event_type]:
            handler(event)
        return event


event_bus = EventBus()
