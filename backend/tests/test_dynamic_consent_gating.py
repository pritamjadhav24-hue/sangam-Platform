"""Phase 3: consent gating in the dependency/provider execution path.

Uses the exact existing versioned-consent implementation (app.engine.consent_manager,
ConsentRow.version, execute_with_persisted_authorization) through
dependency_orchestrator.initiate_dependency -- the real call site a provider
execution goes through. No new consent model or scoping rule is introduced.
"""
import unittest
from datetime import datetime, timedelta, timezone

from app.core.demo_state import reset_demo_state
from app.core.persistence import ConsentRow, Session, engine
from app.engine.adapters import set_integration_availability
from app.engine.consent_manager import ConsentAuthorizationError, create_consent, revoke_consent
from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency


def _app(app_id, requirement_code, consent_id=None):
    return {
        "appId": app_id,
        "citizenId": "CITIZEN_001",
        "status": "WAITING_FOR_DEPENDENCY",
        "dependencyIds": [],
        "dependencies": [],
        "requirements": [{"code": requirement_code, "status": "MISSING"}],
        "entityReviews": [],
        "conflictReviews": [],
        "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
        "consentId": consent_id,
    }


class ConsentGatingTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        set_integration_availability("Education Department", True)

    def test_missing_consent_fails_closed_before_any_provider_call(self):
        app = _app("PHASE3-CONSENT-MISSING", "ACADEMIC_RECORD")  # no consentId at all
        ensure_dependency(app, "ACADEMIC_RECORD")
        with self.assertRaises(ConsentAuthorizationError):
            initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")
        dependency = app["dependencies"][0]
        self.assertNotEqual(dependency["status"], "COMPLETED")
        self.assertIsNone(dependency["resultReference"])

    def test_unknown_consent_id_fails_closed(self):
        app = _app("PHASE3-CONSENT-UNKNOWN", "ACADEMIC_RECORD", consent_id="CR-DOES-NOT-EXIST")
        ensure_dependency(app, "ACADEMIC_RECORD")
        with self.assertRaises(ConsentAuthorizationError):
            initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")

    def test_revoked_consent_fails_closed(self):
        receipt = create_consent("CITIZEN_001", True)
        revoke_consent("CITIZEN_001", receipt["consentId"])
        app = _app("PHASE3-CONSENT-REVOKED", "ACADEMIC_RECORD", consent_id=receipt["consentId"])
        ensure_dependency(app, "ACADEMIC_RECORD")
        with self.assertRaises(ConsentAuthorizationError):
            initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")

    def test_expired_consent_fails_closed(self):
        receipt = create_consent("CITIZEN_001", True)
        with Session(engine) as session:
            row = session.get(ConsentRow, receipt["consentId"])
            payload = dict(row.payload)
            payload["expiresAt"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            row.payload = payload
            session.commit()
        app = _app("PHASE3-CONSENT-EXPIRED", "ACADEMIC_RECORD", consent_id=receipt["consentId"])
        ensure_dependency(app, "ACADEMIC_RECORD")
        with self.assertRaises(ConsentAuthorizationError):
            initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")

    def test_consent_bound_to_a_different_application_fails_closed(self):
        receipt = create_consent("CITIZEN_001", True)
        with Session(engine) as session:
            row = session.get(ConsentRow, receipt["consentId"])
            payload = dict(row.payload)
            payload["applicationId"] = "SOME-OTHER-APP-ID"
            row.payload = payload
            session.commit()
        app = _app("PHASE3-CONSENT-WRONG-APP", "ACADEMIC_RECORD", consent_id=receipt["consentId"])
        ensure_dependency(app, "ACADEMIC_RECORD")
        with self.assertRaises(ConsentAuthorizationError):
            initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")

    def test_valid_consent_allows_the_provider_call_to_proceed(self):
        receipt = create_consent("CITIZEN_001", True)
        app = _app("PHASE3-CONSENT-VALID", "ACADEMIC_RECORD", consent_id=receipt["consentId"])
        ensure_dependency(app, "ACADEMIC_RECORD")
        result = initiate_dependency("CITIZEN_001", app, "ACADEMIC_RECORD")
        self.assertTrue(result["success"])
        self.assertEqual(app["dependencies"][0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
