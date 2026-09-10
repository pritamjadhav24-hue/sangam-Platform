from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class AuditBus:
    """Append-only hash-chained ledger. Payloads are represented only by their hash."""
    def __init__(self):
        self.entries: list[dict[str, Any]] = []
        self._processed_event_ids: set[str] = set()

    def append(self, who: str, what: str, why: str, source: str, action: str,
               consent_id: str | None = None, payload: Any = None,
               correlation_id: str | None = None) -> dict[str, Any]:
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        previous_hash = self.entries[-1]["entryHash"] if self.entries else "GENESIS"
        entry = {
            "sequence": len(self.entries) + 1, "who": who, "what": what, "why": why,
            "when": datetime.now(timezone.utc).isoformat(), "source": source, "action": action,
            "consentId": consent_id, "correlationId": correlation_id,
            "payloadHash": payload_hash, "previousHash": previous_hash,
        }
        entry["entryHash"] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous = "GENESIS"
        for entry in self.entries:
            content = {k: v for k, v in entry.items() if k != "entryHash"}
            if entry["previousHash"] != previous or hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest() != entry["entryHash"]:
                return False
            previous = entry["entryHash"]
        return True

    def handle_event(self, event: dict[str, Any]) -> None:
        """Record workflow status events without storing their sensitive payload."""
        event_id = event.get("eventId")
        if event_id and event_id in self._processed_event_ids:
            return
        payload = event.get("payload", {})
        self.append(
            payload.get("actor") or event.get("actor") or "SYSTEM",
            "APPLICATION",
            "Workflow state transition",
            event.get("source", "workflow_engine"),
            payload.get("status", event.get("type", "EVENT")),
            payload.get("consentId"),
            {"eventId": event_id, "appId": event.get("applicationId"), "status": payload.get("status")},
            event.get("correlationId"),
        )
        if event_id:
            self._processed_event_ids.add(event_id)

    def reset(self) -> None:
        self.entries.clear()
        self._processed_event_ids.clear()


audit_bus = AuditBus()

from app.core.event_bus import event_bus
event_bus.subscribe("APPLICATION_STATUS_CHANGED", audit_bus.handle_event)
