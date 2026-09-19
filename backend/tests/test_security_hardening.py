import unittest

from fastapi import HTTPException

from app.core.data_safety import redact, safe_error_message
from app.core.demo_state import reset_demo_state
from app.core.event_bus import event_bus
from app.core.audit_bus import audit_bus
from app.core.notification_manager import notification_manager
from app.core.rate_limit import enforce, reset as reset_rate_limit
from app.engine.consent_manager import CONSUMER, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent
from app.api.citizen_routes import get_citizen_application
from app.engine.workflow_engine import APPLICATIONS


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        reset_rate_limit()

    def test_recursive_redaction_preserves_operational_metadata(self):
        value = {"jobId": "JOB-1", "nested": [{"phone": "9000000001", "safe": "AVAILABLE"}], "credentials": {"client_secret": "never"}}
        safe = redact(value)
        self.assertEqual(safe["jobId"], "JOB-1")
        self.assertEqual(safe["nested"][0]["phone"], "[REDACTED]")
        self.assertEqual(safe["credentials"], "[REDACTED]")

    def test_event_ledger_is_safe_but_routing_notifications_still_work(self):
        event_bus.publish("APPLICATION_STATUS_CHANGED", {"appId": "APP-SEC", "citizenId": "CITIZEN_001", "phone": "9000000001", "status": "WAITING_FOR_OFFICER"})
        stored = event_bus.events[-1]
        self.assertNotIn("citizenId", stored["payload"])
        self.assertNotIn("phone", stored["payload"])
        self.assertTrue(notification_manager.notifications)
        self.assertTrue(any(item["recipientUserId"] == "CITIZEN_001" for item in notification_manager.notifications))
        audit_bus.append("CITIZEN_001", "APPLICATION", "test", "test", "READ", payload={"status": "SAFE"})
        self.assertNotIn("CITIZEN_001", str(audit_bus.entries[-1]))

    def test_consent_is_bound_to_service_and_application(self):
        receipt = create_consent("CITIZEN_001", True, service_id="SERVICE-A", application_id="APP-A")
        self.assertEqual(authorize_access("CITIZEN_001", CONSUMER, PURPOSE, service_id="SERVICE-A", application_id="APP-A")["consentId"], receipt["consentId"])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_access("CITIZEN_001", CONSUMER, PURPOSE, service_id="SERVICE-B", application_id="APP-A")
        with self.assertRaises(ConsentAuthorizationError):
            authorize_access("CITIZEN_001", CONSUMER, PURPOSE, service_id="SERVICE-A", application_id="APP-B")

    def test_rate_limit_is_bounded_and_returns_429(self):
        enforce("security_test", "citizen-a", limit=2, window_seconds=60)
        enforce("security_test", "citizen-a", limit=2, window_seconds=60)
        with self.assertRaises(HTTPException) as context:
            enforce("security_test", "citizen-a", limit=2, window_seconds=60)
        self.assertEqual(context.exception.status_code, 429)

    def test_provider_error_is_sanitized(self):
        message = safe_error_message("Traceback SQLAlchemy password=topsecret raw HTTP response body {aadhaar: 1234}")
        self.assertNotIn("topsecret", message)
        self.assertNotIn("1234", message)
        self.assertEqual(message, "Upstream operation failed.")

    def test_citizen_cannot_use_another_citizens_application_id(self):
        APPLICATIONS["APP-OWNER"] = {"appId": "APP-OWNER", "citizenId": "CITIZEN_001", "requirements": [], "dependencies": [], "conflicts": []}
        with self.assertRaises(HTTPException) as context:
            get_citizen_application("APP-OWNER", {"role": "CITIZEN", "citizenId": "CITIZEN_002"})
        self.assertEqual(context.exception.status_code, 404)

    def test_safe_application_view_does_not_return_raw_requirement_records(self):
        from app.api.citizen_routes import _safe_application
        safe = _safe_application({"appId": "APP-SAFE", "citizenId": "CITIZEN_001", "requirements": [{"code": "INCOME_PROOF", "source": "Revenue Department", "status": "FOUND", "canonical": {"incomeAmount": 123}, "recordId": "RAW-1"}], "dependencies": [], "conflicts": []})
        self.assertEqual(safe["requirements"], [{"requirementCode": "INCOME_PROOF", "displayLabel": "Income Proof", "status": "FOUND", "userAction": "No action required"}])
        self.assertNotIn("recordId", str(safe))
        self.assertNotIn("canonical", str(safe))

    def test_safe_application_view_hides_provider_operational_metadata(self):
        from app.api.citizen_routes import _safe_application
        safe = _safe_application({"appId": "APP-SAFE", "requirements": [], "dependencies": [{
            "dependencyId": "DEP-1", "requiredService": "Income verification", "providerStatus": "AVAILABLE",
            "resultReference": "INTERNAL-123", "lastError": "provider stack trace", "errorCategory": "INTERNAL_ERROR",
            "status": "COMPLETED", "attempts": 1, "maxAttempts": 3,
        }], "conflicts": []})
        text = str(safe)
        self.assertNotIn("INTERNAL-123", text)
        self.assertNotIn("provider stack trace", text)
        self.assertNotIn("providerStatus", text)
        self.assertNotIn("errorCategory", text)

    def test_safe_discovery_view_contains_only_citizen_actionable_fields(self):
        from app.api.citizen_routes import _safe_discovery
        safe = _safe_discovery({
            "schemeId": "SERVICE-1", "serviceId": "SERVICE-1",
            "service": {"serviceId": "SERVICE-1", "name": "Configured service", "department": "Configured department"},
            "requirements": [{"code": "INCOME_PROOF", "status": "FOUND", "canonical": {"income": 10}, "recordId": "RAW-1", "mappingEvidence": [{"sourceField": "x"},], "resolution": {"score": 1}}],
            "mappingEvidence": [{"sourceRecordId": "RAW-1"}], "semanticMappingEvidence": [{"internal": True}], "conflicts": [],
        })
        text = str(safe)
        self.assertEqual(safe["requirements"][0]["requirementCode"], "INCOME_PROOF")
        self.assertNotIn("RAW-1", text)
        self.assertNotIn("canonical", text)
        self.assertNotIn("mappingEvidence", text)
        self.assertNotIn("resolution", text)


if __name__ == "__main__":
    unittest.main()
