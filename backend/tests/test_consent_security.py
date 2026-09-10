import unittest
from datetime import datetime, timedelta, timezone

from app.core.demo_state import reset_demo_state
from app.core.persistence import hydrate_state, persist_state
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent, revoke_consent


class ConsentSecurityTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_missing_wrong_purpose_disallowed_attribute_expired_and_revoked(self):
        with self.assertRaises(ConsentAuthorizationError):
            authorize_access("CITIZEN_001", CONSUMER, PURPOSE, PERMITTED)
        receipt = create_consent("CITIZEN_001", True, [PERMITTED[0]])
        self.assertEqual(authorize_access("CITIZEN_001", CONSUMER, PURPOSE, [PERMITTED[0]])["consentId"], receipt["consentId"])
        with self.assertRaises(ConsentAuthorizationError): authorize_access("CITIZEN_001", CONSUMER, "Different purpose")
        with self.assertRaises(ConsentAuthorizationError): authorize_access("CITIZEN_001", CONSUMER, PURPOSE, [PERMITTED[1]])
        receipt["expiresAt"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.assertRaises(ConsentAuthorizationError): authorize_access("CITIZEN_001", CONSUMER, PURPOSE, [PERMITTED[0]])
        receipt["expiresAt"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        revoke_consent("CITIZEN_001", receipt["consentId"])
        with self.assertRaises(ConsentAuthorizationError): authorize_access("CITIZEN_001", CONSUMER, PURPOSE, [PERMITTED[0]])

    def test_consent_persists_and_hydrates(self):
        receipt = create_consent("CITIZEN_001", True)
        persist_state()
        from app.engine import consent_manager
        consent_manager.CONSENTS.clear(); hydrate_state()
        self.assertEqual(consent_manager.CONSENTS["CITIZEN_001"]["consentId"], receipt["consentId"])


if __name__ == "__main__":
    unittest.main()
