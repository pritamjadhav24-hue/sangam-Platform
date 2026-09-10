import unittest

from app.core.demo_state import reset_demo_state
from app.core.event_bus import EVENT_TYPES, event_bus
from app.core.notification_manager import notification_manager
from app.core.persistence import EventRow, engine, hydrate_state, persist_state
from sqlalchemy import select


class EventDrivenTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_event_envelope_and_canonical_types(self):
        event = event_bus.publish("APPLICATION_STATUS_CHANGED", {"appId": "APP-EVENT-1", "status": "WAITING_FOR_OFFICER", "actor": "SYSTEM"})
        self.assertTrue(event["eventId"].startswith("EVT-"))
        self.assertEqual(event["applicationId"], "APP-EVENT-1")
        self.assertEqual(event["correlationId"], "APP-EVENT-1")
        self.assertEqual(event["actor"], "SYSTEM")
        self.assertIn("APPLICATION_STATUS_CHANGED", EVENT_TYPES)

    def test_notification_duplicate_delivery_is_idempotent(self):
        event = event_bus.publish("APPLICATION_STATUS_CHANGED", {"appId": "APP-EVENT-2", "citizenId": "CITIZEN_001", "status": "WAITING_FOR_OFFICER"})
        count = len(notification_manager.notifications)
        event_bus.dispatch(event)
        notification_manager.handle(event)
        self.assertEqual(len(notification_manager.notifications), count)
        self.assertEqual(len({item["notificationId"] for item in notification_manager.notifications}), count)

    def test_event_persistence_hydration_and_ordering(self):
        app_id = "APP-EVENT-3"
        first = event_bus.publish("DEPENDENCY_CREATED", {"appId": app_id, "dependencyId": "DEP-1"})
        second = event_bus.publish("REVENUE_SERVICE_REQUESTED", {"appId": app_id, "dependencyId": "DEP-1"})
        third = event_bus.publish("DOMICILE_ISSUED", {"appId": app_id, "dependencyId": "DEP-1"})
        persist_state()
        with engine.connect() as connection:
            rows = connection.execute(select(EventRow).where(EventRow.app_id == app_id).order_by(EventRow.id)).all()
            self.assertEqual([row.event_type for row in rows], ["DEPENDENCY_CREATED", "REVENUE_SERVICE_REQUESTED", "DOMICILE_ISSUED"])
        event_bus.reset(); hydrate_state()
        hydrated = [event for event in event_bus.events if event.get("applicationId") == app_id]
        self.assertEqual([event["eventId"] for event in hydrated], [first["eventId"], second["eventId"], third["eventId"]])
        self.assertEqual([event["type"] for event in hydrated], ["DEPENDENCY_CREATED", "REVENUE_SERVICE_REQUESTED", "DOMICILE_ISSUED"])

    def test_duplicate_handler_delivery_does_not_repeat_irreversible_action(self):
        calls = []
        def handler(event): calls.append(event["eventId"])
        event_bus.subscribe("WORKFLOW_RESUMED", handler)
        event = event_bus.publish("WORKFLOW_RESUMED", {"appId": "APP-EVENT-4", "status": "IN_PROGRESS"})
        event_bus.dispatch(event)
        self.assertEqual(calls, [event["eventId"]])

    def test_event_correlation_and_audit_compatibility(self):
        event = event_bus.publish("APPLICATION_SUBMITTED", {"appId": "APP-EVENT-5", "consentId": "CONSENT-1"})
        self.assertEqual(event["correlationId"], "APP-EVENT-5")
        self.assertEqual(event["payload"]["consentId"], "CONSENT-1")


if __name__ == "__main__":
    unittest.main()
