from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus


_availability = {}
_last_health = {}
_integrations = {
    "Civil Registry": {"adapterType": "Federated SSO", "service": "Identity verification"},
    "Revenue Department": {"adapterType": "REST API", "service": "Income and domicile services"},
    "Social Welfare Department": {"adapterType": "Legacy SOAP Wrapper", "service": "Caste verification"},
    "Education Department": {"adapterType": "CSV/File Adapter", "service": "Academic records"},
    "Authorized DBT": {"adapterType": "REST API", "service": "Bank account verification"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_integration_availability(source: str, available: bool, error: str | None = None) -> dict:
    if source not in _integrations:
        raise KeyError(f"Unknown integration: {source}")
    _availability[source] = {"available": available, "error": error if not available else None}
    snapshot = integration_health(record_event=True)
    return next(item for item in snapshot if item["system"] == source)


def is_integration_available(source: str) -> bool:
    return _availability.get(source, {"available": True})["available"]


def integration_health(record_event: bool = False) -> list[dict]:
    checked_at = _now()
    result = []
    for system, metadata in _integrations.items():
        state = _availability.get(system, {"available": True, "error": None})
        status = "AVAILABLE" if state["available"] else "UNAVAILABLE"
        item = {
            "system": system,
            "department": system,
            "adapterType": metadata["adapterType"],
            "service": metadata["service"],
            "status": status,
            "lastCheckedAt": checked_at,
            "error": state.get("error"),
        }
        result.append(item)
        if record_event and _last_health.get(system) != status:
            event_bus.publish("INTEGRATION_HEALTH_CHANGED", {"system": system, "status": status, "service": metadata["service"]})
            audit_bus.append("SYSTEM", "INTEGRATION_HEALTH", "Integration availability check", system, status, payload={"system": system, "status": status})
        _last_health[system] = status
    return result


class SourceAdapter:
    kind = "REST"
    def __init__(self, source: str, fetcher: Callable):
        self.source, self.fetcher = source, fetcher
        _integrations.setdefault(source, {"adapterType": self.kind, "service": "Mock adapter service"})
    def fetch(self, citizen_id: str, simulate_timeout: bool = False):
        for attempt in range(1, 4):
            try:
                if simulate_timeout and attempt == 1:
                    raise TimeoutError("Upstream response timeout")
                record = self.fetcher(citizen_id)
                return {"record": record, "attempts": attempt, "delayed": attempt > 1, "adapter": self.kind}
            except TimeoutError:
                if attempt == 3: return {"record": None, "attempts": attempt, "delayed": True, "queued": True, "adapter": self.kind}
                time.sleep(0.08 * attempt)


class RestAPIAdapter(SourceAdapter): kind = "REST API"
class LegacySOAPAdapter(SourceAdapter): kind = "Legacy SOAP Wrapper"
class CSVFileAdapter(SourceAdapter): kind = "CSV/File Adapter"


def validate_payload(record: dict | None) -> dict:
    if not record: return {"valid": False, "reasons": ["No source record available"]}
    reasons = []
    if not record.get("signature"): reasons.append("Missing source signature")
    if not record.get("validUntil"): reasons.append("Missing validity period")
    return {"valid": not reasons, "reasons": reasons}
