import unittest

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.event_bus import event_bus
from app.core.notification_manager import notification_manager
from app.core.persistence import persist_state
from app.engine.adapters import set_integration_availability
from app.engine.consent_manager import create_consent
from app.engine.dependency_orchestrator import ensure_domicile_dependency, initiate_domicile
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import create_application, officer_action, transition_application
from app.mocks.identity_provider import CITIZENS


class GoldenRegressionTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        set_integration_availability("Revenue Department", True)

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def _journey(self):
        citizen_id = "CITIZEN_001"
        citizen = CITIZENS[citizen_id]
        receipt = create_consent(citizen_id, True)
        result = discover(citizen)
        app = create_application(citizen_id, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        dependency = ensure_domicile_dependency(app)
        return citizen_id, receipt, app, dependency

    def test_complete_golden_path_preserves_identity_links(self):
        citizen_id, receipt, app, dependency = self._journey()
        issued = initiate_domicile(citizen_id, app)
        self.assertTrue(issued["success"])
        refreshed = discover(CITIZENS[citizen_id])
        app["requirements"] = refreshed["requirements"]
        app["eligibility"] = evaluate(app["requirements"])
        transition_application(app, "SUBMITTED")
        transition_application(app, "WAITING_FOR_OFFICER")
        officer_action(app["appId"], "APPROVE", "Automated regression approval")
        self.assertEqual(app["status"], "COMPLETED")
        self.assertEqual(app["consentId"], receipt["consentId"])
        self.assertEqual(app["dependencyIds"], [dependency["dependencyId"]])
        self.assertEqual(app["dependencies"][0]["dependencyId"], dependency["dependencyId"])
        self.assertEqual([item["status"] for item in app["statusHistory"]][-5:], ["WAITING_FOR_DEPENDENCY", "IN_PROGRESS", "SUBMITTED", "WAITING_FOR_OFFICER", "APPROVED"] if app["statusHistory"][-1]["status"] != "COMPLETED" else ["IN_PROGRESS", "SUBMITTED", "WAITING_FOR_OFFICER", "APPROVED", "COMPLETED"])
        app_events = [event for event in event_bus.events if event.get("applicationId") == app["appId"]]
        self.assertTrue(app_events)
        self.assertTrue(all(event.get("correlationId") == app["appId"] for event in app_events if event.get("applicationId") == app["appId"]))
        self.assertTrue(notification_manager.notifications)
        self.assertTrue(audit_bus.verify())

    def test_revenue_failure_retry_recovery_is_same_dependency_and_idempotent(self):
        citizen_id, _, app, dependency = self._journey()
        set_integration_availability("Revenue Department", False, "test outage")
        first = initiate_domicile(citizen_id, app)
        second = initiate_domicile(citizen_id, app)
        set_integration_availability("Revenue Department", True)
        recovered = initiate_domicile(citizen_id, app)
        repeated = initiate_domicile(citizen_id, app)
        self.assertEqual(first["dependencyId"], dependency["dependencyId"])
        self.assertEqual(second["dependencyId"], dependency["dependencyId"])
        self.assertEqual(recovered["dependencyId"], dependency["dependencyId"])
        self.assertTrue(recovered["success"])
        self.assertTrue(repeated["success"])
        self.assertEqual(dependency["attempts"], 3)
        self.assertEqual(len(app["dependencies"]), 1)
        self.assertEqual(len([event for event in event_bus.events if event["type"] == "DOMICILE_ISSUED"]), 1)
        self.assertTrue(audit_bus.verify())


if __name__ == "__main__":
    unittest.main()
