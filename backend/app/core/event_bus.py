from collections import defaultdict
from datetime import datetime, timezone
import secrets
from typing import Any, Callable

EVENT_TYPES = frozenset({
    "APPLICATION_CREATED", "APPLICATION_STATUS_CHANGED", "CONSENT_GRANTED", "CONSENT_REVOKED",
    "DEPENDENCY_CREATED", "DEPENDENCY_STATUS_CHANGED", "REVENUE_SERVICE_REQUESTED", "DOMICILE_ISSUED",
    "WORKFLOW_RESUMED", "APPLICATION_SUBMITTED", "OFFICER_ACTION", "ENTITY_REVIEW_CREATED",
    "ENTITY_REVIEW_RESOLVED", "CONFLICT_DETECTED", "CONFLICT_RESOLVED", "INTEGRATION_HEALTH_CHANGED",
    "RETRY_SCHEDULED", "RETRY_SUCCEEDED", "NOTIFICATION_CREATED",
    "MISSING_PREREQUISITE_DETECTED", "PROVIDER_SELECTED", "DEPENDENCY_RESOLVED", "DEPENDENCY_SERVICE_FAILED",
    "DEPENDENCY_RETRY_SCHEDULED", "DEPENDENCY_RECOVERED", "ENTITY_MATCH_REVIEW_REQUIRED", "ENTITY_MATCH_DECIDED",
    "OFFICER_ENTITY_REVIEW_ACTION", "OFFICER_CONFLICT_REVIEW_ACTION", "APPLICATION_COMPLETED", "APPLICATION_REJECTED",
    "SCHEMA_MAPPING_REVIEW_DECIDED", "IDENTITY_VERIFIED", "INCOME_PROOF_VERIFIED",
})


class EventBus:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._processed_handlers: set[tuple[str, int]] = set()

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            # Existing prototype-specific events remain supported while the
            # canonical set documents the important domain event vocabulary.
            event_type = str(event_type)
        event = {
            "eventId": f"EVT-{secrets.token_hex(8).upper()}",
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "applicationId": payload.get("appId"),
            "correlationId": payload.get("correlationId") or payload.get("appId"),
            "actor": payload.get("actor") or payload.get("actorId") or payload.get("officerId") or "SYSTEM",
            "source": payload.get("source") or "domain",
            "payload": payload,
        }
        self.events.append(event)
        self.dispatch(event)
        return event

    def dispatch(self, event: dict[str, Any]) -> None:
        """Deliver an event once per subscriber; safe for duplicate delivery."""
        event_id = event.get("eventId")
        for handler in self._subscribers[event["type"]]:
            key = (event_id, id(handler)) if event_id else (str(id(event)), id(handler))
            if key in self._processed_handlers:
                continue
            handler(event)
            self._processed_handlers.add(key)

    def hydrate(self, events: list[dict[str, Any]]) -> None:
        self.events.extend(events)
        for event in events:
            event_id = event.get("eventId")
            if event_id:
                for handler in self._subscribers[event.get("type")]:
                    self._processed_handlers.add((event_id, id(handler)))

    def reset(self) -> None:
        self.events.clear()
        self._processed_handlers.clear()


event_bus = EventBus()
