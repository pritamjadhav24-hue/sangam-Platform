from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.mocks.identity_provider import USERS


class NotificationManager:
    def __init__(self):
        self.notifications: list[dict] = []
        self._counter = itertools.count(1)
        self._processed_event_ids: set[str] = set()

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
            "sourceEventId": payload.get("eventId"),
            # Operational notifications say where to go (provider, incident,
            # application) and how serious it is; citizen ones leave these out.
            **({"target": payload["target"]} if isinstance(payload.get("target"), dict) else {}),
            **({"severity": payload["severity"]} if payload.get("severity") else {}),
        }
        if item["sourceEventId"] and any(existing.get("recipientUserId") == recipient_user_id and existing.get("sourceEventId") == item["sourceEventId"] for existing in self.notifications):
            return next(existing for existing in self.notifications if existing.get("recipientUserId") == recipient_user_id and existing.get("sourceEventId") == item["sourceEventId"])
        self.notifications.append(item)
        event_bus.publish("NOTIFICATION_CREATED", {"notificationId": item["notificationId"], "appId": item.get("applicationId"), "correlationId": item.get("correlationId"), "recipientRole": role, "source": "notification_manager"})
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
        event_id = event.get("eventId")
        if event_id and event_id in self._processed_event_ids:
            return
        if event_id:
            payload = {**payload, "eventId": event_id}
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
        elif event_type in {"DEPENDENCY_SERVICE_FAILED", "DEPENDENCY_RETRY_SCHEDULED", "PROVIDER_JOB_DEAD_LETTER"}:
            self._citizen(payload, "INTEGRATION_FAILURE", "Department service unavailable", "A required department service is unavailable; your application remains waiting for retry.")
            self._role("ADMIN", "INTEGRATION_FAILURE", "Department request failed",
                       f"A department request{' for ' + app_id if app_id else ''} failed and is waiting to be retried.",
                       {**payload, "eventId": f"DEPENDENCY_FAILED:{app_id}:{payload.get('dependencyId')}", "severity": "WARNING",
                        **({"target": {"kind": "application", "applicationId": app_id}} if app_id else {})})  # once per failing dependency, not per retry
        elif event_type == "DEPENDENCY_RECOVERED":
            self._citizen(payload, "INTEGRATION_RECOVERY", "Department service recovered", "The required department service recovered and processing resumed.")
            self._role("ADMIN", "INTEGRATION_RECOVERY", "Department request recovered",
                       f"A department request{' for ' + app_id if app_id else ''} completed after recovery.",
                       {**payload, "eventId": f"DEPENDENCY_RECOVERED:{app_id}:{payload.get('dependencyId')}", "severity": "SUCCESS",
                        **({"target": {"kind": "application", "applicationId": app_id}} if app_id else {})})
        elif event_type in {"ENTITY_MATCH_REVIEW_REQUIRED", "CONFLICT_DETECTED"}:
            self._role("OFFICER", "OFFICER_REVIEW_REQUIRED", "Officer review required", "A cross-system verification item requires your decision.", payload)
        # INTEGRATION_HEALTH_CHANGED no longer notifies administrators directly:
        # the provider incident it opens or resolves does (PROVIDER_DOWN /
        # PROVIDER_RECOVERED, with a link to the incident), so an outage is
        # announced once, not twice.
        if event_id:
            self._processed_event_ids.add(event_id)

    def operational(self, notification_type: str, title: str, message: str, *, dedupe_key: str,
                    target: dict | None = None, severity: str = "INFO", app_id: str | None = None) -> None:
        """An operations notification for every administrator: an outage,
        recovery, fallback, blocked application or integration error. Each
        carries a navigation target, and ``dedupe_key`` makes it one
        notification per real occurrence (never one per poll or retry)."""
        # The application goes in the target, not the top-level applicationId:
        # the legacy state snapshot skips rows keyed to authoritative
        # applications, which would drop these notices (and their read state)
        # on restart.
        target = {**(target or {}), **({"applicationId": app_id} if app_id and "applicationId" not in (target or {}) else {})}
        payload = {"eventId": dedupe_key, "target": target, "severity": severity, "correlationId": app_id}
        self._role("ADMIN", notification_type, title, message, payload)

    def for_user(self, user: dict) -> list[dict]:
        return [item for item in reversed(self.notifications) if item["recipientUserId"] == user["userId"] and item["role"] == user["role"]]

    def mark_all_read(self, user: dict) -> int:
        changed = 0
        for item in self.notifications:
            if item["recipientUserId"] == user["userId"] and item["role"] == user["role"] and not item.get("read"):
                item["read"] = True
                changed += 1
        return changed

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
    "DEPENDENCY_RETRY_SCHEDULED", "DEPENDENCY_RECOVERED", "PROVIDER_JOB_DEAD_LETTER", "ENTITY_MATCH_REVIEW_REQUIRED", "CONFLICT_DETECTED",
    "INTEGRATION_HEALTH_CHANGED",
]:
    event_bus.subscribe(_event_name, notification_manager.handle)
