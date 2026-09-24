import unittest
import uuid
from datetime import datetime, timedelta, timezone

from app.core.demo_state import reset_demo_state
from app.core.persistence import ConsentRow, engine, hydrate_state, persist_state
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, authorize_persisted_access, create_consent, revoke_consent
from sqlalchemy.orm import Session


class ConsentSecurityTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def _historical_rows(self, citizen_id, rows):
        with Session(engine) as session:
            for consent_id, payload in rows:
                session.add(ConsentRow(consent_id=consent_id, citizen_id=citizen_id, payload=payload))
            session.commit()

    def _payload(self, consent_id, citizen_id, decision="ALLOW", application_id=None, expires_at=None, revoked_at=None):
        payload = {"consentId": consent_id, "citizenId": citizen_id, "consumer": CONSUMER, "purpose": PURPOSE,
                   "allowed": list(PERMITTED), "decision": decision,
                   "expiresAt": expires_at or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        if application_id is not None:
            payload["applicationId"] = application_id
        if revoked_at is not None:
            payload["revokedAt"] = revoked_at
        return payload

    def test_exact_active_consent_wins_over_older_revoked_row(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        old_id, new_id = "CR-OLD-REVOKED-" + uuid.uuid4().hex, "CR-NEW-ACTIVE-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(old_id, self._payload(old_id, citizen_id, "REVOKED", revoked_at="2026-01-01T00:00:00+00:00")), (new_id, self._payload(new_id, citizen_id))])
        self.assertEqual(authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id=new_id)["consentId"], new_id)

    def test_multiple_active_consents_without_id_fail_closed(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        first, second = "CR-ACTIVE-A-" + uuid.uuid4().hex, "CR-ACTIVE-B-" + uuid.uuid4().hex
        rows = [(first, self._payload(first, citizen_id)), (second, self._payload(second, citizen_id))]
        self._historical_rows(citizen_id, rows)
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE)

    def test_historical_revoked_and_active_consents_without_id_fail_closed(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        revoked_id, active_id = "CR-REVOKED-HISTORY-" + uuid.uuid4().hex, "CR-ACTIVE-HISTORY-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(revoked_id, self._payload(revoked_id, citizen_id, "REVOKED", revoked_at="2026-01-01T00:00:00+00:00")), (active_id, self._payload(active_id, citizen_id))])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE)

    def test_historical_expired_and_active_consents_without_id_fail_closed(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        expired_id, active_id = "CR-EXPIRED-HISTORY-" + uuid.uuid4().hex, "CR-ACTIVE-HISTORY-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(expired_id, self._payload(expired_id, citizen_id, expires_at="2020-01-01T00:00:00+00:00")), (active_id, self._payload(active_id, citizen_id))])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE)

    def test_exact_new_active_consent_ignores_older_expired_row(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        old_id, new_id = "CR-OLD-EXPIRED-" + uuid.uuid4().hex, "CR-NEW-ACTIVE-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(old_id, self._payload(old_id, citizen_id, expires_at="2020-01-01T00:00:00+00:00")), (new_id, self._payload(new_id, citizen_id))])
        self.assertEqual(authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id=new_id)["consentId"], new_id)

    def test_missing_exact_consent_id_fails(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id="CR-NOT-PRESENT")

    def test_exact_consent_belonging_to_another_citizen_fails(self):
        owner = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        other = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        consent_id = "CR-OTHER-" + uuid.uuid4().hex
        self._historical_rows(owner, [(consent_id, self._payload(consent_id, owner))])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(other, CONSUMER, PURPOSE, consent_id=consent_id)

    def test_exact_revoked_consent_fails(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        consent_id = "CR-REVOKED-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(consent_id, self._payload(consent_id, citizen_id, "REVOKED", revoked_at="2026-01-01T00:00:00+00:00"))])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id=consent_id)

    def test_exact_expired_consent_fails(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        consent_id = "CR-EXPIRED-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(consent_id, self._payload(consent_id, citizen_id, expires_at="2020-01-01T00:00:00+00:00"))])
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id=consent_id)

    def test_exact_consent_prevents_cross_application_selection(self):
        citizen_id = f"CITIZEN-CONSENT-{uuid.uuid4().hex}"
        app_a, app_b = "APP-A-" + uuid.uuid4().hex, "APP-B-" + uuid.uuid4().hex
        consent_a, consent_b = "CR-APP-A-" + uuid.uuid4().hex, "CR-APP-B-" + uuid.uuid4().hex
        self._historical_rows(citizen_id, [(consent_a, self._payload(consent_a, citizen_id, application_id=app_a)), (consent_b, self._payload(consent_b, citizen_id, application_id=app_b))])
        self.assertEqual(authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, application_id=app_b, consent_id=consent_b)["consentId"], consent_b)
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, application_id=app_a, consent_id=consent_b)

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
        self.assertEqual(consent_manager.CONSENTS_BY_ID[receipt["consentId"]]["consentId"], receipt["consentId"])


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
