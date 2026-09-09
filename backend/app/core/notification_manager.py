from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.mocks.identity_provider import USERS


class NotificationManager:
    def __init__(self):
        self.notifications: list[dict] = []
        self._counter = itertools.count(1)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def add(self, recipient_user_id: str, role: str, notification_type: str, title: str, message: str, payload: dict) -> dict:
        item = {
            "notificationId": f"NTF-{next(self._counter):05d}",
            "recipientUserId": recipient_user_id,
            "role": role,
            "type": notification_type,
            "title": title,
            "message": message,
            "applicationId": payload.get("appId"),
            "correlationId": payload.get("appId") or payload.get("correlationId"),
            "createdAt": self._now(),
            "read": False,
        }
        self.notifications.append(item)
        return item

    def _citizen(self, payload: dict, notification_type: str, title: str, message: str) -> None:
        citizen_id = payload.get("citizenId")
        if citizen_id:
            self.add(citizen_id, "CITIZEN", notification_type, title, message, payload)

    def _role(self, role: str, notification_type: str, title: str, message: str, payload: dict) -> None:
        for user in USERS.values():
            if user.get("role") == role:
                self.add(user["userId"], role, notification_type, title, message, payload)

    def handle(self, event: dict) -> None:
        event_type, payload = event["type"], event.get("payload", {})
        app_id = payload.get("appId")
        if event_type == "APPLICATION_STATUS_CHANGED":
            status = payload.get("status", "").replace("_", " ")
            self._citizen(payload, "APPLICATION_STATUS", "Application status updated", f"Your application is now {status}.")
            if payload.get("status") == "WAITING_FOR_OFFICER":
                self._role("OFFICER", "OFFICER_REVIEW_REQUIRED", "Application needs review", "An application is waiting for officer review.", payload)
        elif event_type == "DEPENDENCY_CREATED":
            self._citizen(payload, "DEPENDENCY_WAITING", "Dependency created", "A required department service has been requested for your application.")
        elif event_type in {"DOMICILE_ISSUED", "DEPENDENCY_RESOLVED"}:
            self._citizen(payload, "DEPENDENCY_RESOLVED", "Dependency resolved", "The required department service completed and your application can continue.")
        elif event_type == "APPLICATION_SUBMITTED":
            self._citizen(payload, "APPLICATION_SUBMITTED", "Application submitted", "Your application was submitted for officer review.")
            self._role("OFFICER", "OFFICER_REVIEW_REQUIRED", "Application submitted for review", "A submitted application is ready for officer action.", payload)
        elif event_type == "APPLICATION_COMPLETED":
            self._citizen(payload, "APPLICATION_COMPLETED", "Application completed", "Your application journey has completed successfully.")
        elif event_type == "APPLICATION_REJECTED":
            self._citizen(payload, "APPLICATION_REJECTED", "Application rejected", "Your application was rejected after review.")
        elif event_type in {"DEPENDENCY_SERVICE_FAILED", "DEPENDENCY_RETRY_SCHEDULED"}:
            self._citizen(payload, "INTEGRATION_FAILURE", "Department service unavailable", "A required department service is unavailable; your application remains waiting for retry.")
            self._role("ADMIN", "INTEGRATION_FAILURE", "Integration failure", "A simulated department service reported a dependency failure.", payload)
        elif event_type == "DEPENDENCY_RECOVERED":
            self._citizen(payload, "INTEGRATION_RECOVERY", "Department service recovered", "The required department service recovered and processing resumed.")
            self._role("ADMIN", "INTEGRATION_RECOVERY", "Integration recovered", "A simulated department service recovered.", payload)
        elif event_type in {"ENTITY_MATCH_REVIEW_REQUIRED", "CONFLICT_DETECTED"}:
            self._role("OFFICER", "OFFICER_REVIEW_REQUIRED", "Officer review required", "A cross-system verification item requires your decision.", payload)
        elif event_type == "INTEGRATION_HEALTH_CHANGED":
            notification_type = "INTEGRATION_RECOVERY" if payload.get("status") == "AVAILABLE" else "INTEGRATION_FAILURE"
            title = "Integration recovered" if payload.get("status") == "AVAILABLE" else "Integration unavailable"
            self._role("ADMIN", notification_type, title, f"{payload.get('system', 'A department')} is {payload.get('status', '').lower()}.", payload)

    def for_user(self, user: dict) -> list[dict]:
        return [item for item in reversed(self.notifications) if item["recipientUserId"] == user["userId"] and item["role"] == user["role"]]

    def mark_read(self, notification_id: str, user: dict) -> dict | None:
        item = next((entry for entry in self.notifications if entry["notificationId"] == notification_id), None)
        if not item or item["recipientUserId"] != user["userId"] or item["role"] != user["role"]:
            return None
        item["read"] = True
        return item


notification_manager = NotificationManager()
for _event_name in [
    "APPLICATION_STATUS_CHANGED", "DEPENDENCY_CREATED", "DOMICILE_ISSUED", "DEPENDENCY_RESOLVED",
    "APPLICATION_SUBMITTED", "APPLICATION_COMPLETED", "APPLICATION_REJECTED", "DEPENDENCY_SERVICE_FAILED",
    "DEPENDENCY_RETRY_SCHEDULED", "DEPENDENCY_RECOVERED", "ENTITY_MATCH_REVIEW_REQUIRED", "CONFLICT_DETECTED",
    "INTEGRATION_HEALTH_CHANGED",
]:
    event_bus.subscribe(_event_name, notification_manager.handle)
