"""Real in-request fallback cascade for the synchronous Auto-Fill path
(app.engine.requirement_fulfillment): on a retryable primary-provider
failure, the SAME fulfill_requirement() call immediately evaluates and
tries the next eligible provider -- the citizen never has to click
Auto-Fill again. Mocking follows the exact pattern already established in
test_requirement_resilience.py: select_dependency_provider and
request_registered_service are patched at the requirement_fulfillment
module reference; find_fallback_candidate is patched at its defining
module (app.engine.retry_policy) since requirement_fulfillment calls it
via the module reference (retry_policy.find_fallback_candidate).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api.citizen_routes import ApplySchemeRequest, apply_to_scheme
from app.core.audit_bus import audit_bus
from app.core.persistence import (
    ApplicationRow, ConsentRow, DocumentRow, RequirementCatalogRow,
    Session, engine, get_application as get_application_raw, seed_requirement_catalog,
)
from app.engine import requirement_fulfillment, retry_policy
from app.engine.adapters import AdapterResult
from app.engine.consent_manager import create_consent


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


def _fake_request():
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace())


def _success(record_id="REC-1", canonical=None, provider_id=None):
    return AdapterResult(
        {"id": record_id, "canonical": canonical or {"value": "ok"}, "validUntil": None}, success=True,
        metadata={"providerId": provider_id} if provider_id else {},
    )


def _failure(category="UPSTREAM_UNAVAILABLE", retryable=True):
    return AdapterResult(None, success=False, error_category=category, retryable=retryable)


PROVIDER_A = {"serviceId": "SVC-A", "providerId": "PROV-A", "provider": "Provider A", "priority": 10}
PROVIDER_B = {"serviceId": "SVC-B", "providerId": "PROV-B", "provider": "Provider B", "priority": 20}
PROVIDER_C = {"serviceId": "SVC-C", "providerId": "PROV-C", "provider": "Provider C", "priority": 30}


_SEEDED_BY_THIS_MODULE: list[str] = []


def setUpModule():
    from unittest.mock import patch as _patch
    with Session(engine) as session:
        existing = {row.requirement_code for row in session.query(RequirementCatalogRow)}
    with _patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
        seed_requirement_catalog()
    with Session(engine) as session:
        _SEEDED_BY_THIS_MODULE.extend(row.requirement_code for row in session.query(RequirementCatalogRow) if row.requirement_code not in existing)


def tearDownModule():
    # Remove only vocabulary rows this module added, never pre-existing
    # catalog data the running demo depends on.
    if not _SEEDED_BY_THIS_MODULE:
        return
    with Session(engine) as session:
        session.query(RequirementCatalogRow).filter(
            RequirementCatalogRow.requirement_code.in_(_SEEDED_BY_THIS_MODULE)
        ).delete(synchronize_session=False)
        session.commit()


class FallbackCascadeTests(unittest.TestCase):
    def setUp(self):
        self._app_ids: list[str] = []
        self._citizen_ids: list[str] = []

    def tearDown(self):
        with Session(engine) as session:
            if self._app_ids:
                session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._app_ids)).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._app_ids)).delete(synchronize_session=False)
            if self._citizen_ids:
                session.query(ConsentRow).filter(ConsentRow.citizen_id.in_(self._citizen_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str = "SCH-MH-2026") -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._app_ids.append(application["appId"])
        self._citizen_ids.append(citizen_id)
        return application

    def _fulfill(self, application_id: str, code: str, citizen_id: str):
        app_snapshot = get_application_raw(application_id)
        receipt = create_consent(
            citizen_id, True, attributes=[], service_id=app_snapshot.get("serviceId"),
            application_id=application_id, purpose=requirement_fulfillment.auto_fill_purpose(code),
        )
        return requirement_fulfillment.fulfill_requirement(app_snapshot, code, citizen_id, receipt["consentId"])

    # 1. Primary succeeds -> no fallback.
    def test_primary_success_never_evaluates_a_fallback(self):
        application = self._apply("CITIZEN_FB_001")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success()) as mock_call, \
             patch.object(retry_policy, "find_fallback_candidate") as mock_fallback:
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_001")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertEqual(requirement["isFallback"], False)
        self.assertEqual(len(requirement["fallbackAttempts"]), 1)
        mock_call.assert_called_once()
        mock_fallback.assert_not_called()

    # 2. Primary fails -> eligible fallback succeeds, in the SAME call.
    def test_primary_failure_falls_back_to_next_eligible_provider_in_one_call(self):
        application = self._apply("CITIZEN_FB_002")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _success(provider_id="PROV-B")]), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=PROVIDER_B):
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_002")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertEqual(requirement["providerId"], "PROV-B")
        self.assertTrue(requirement["isFallback"])
        self.assertEqual(len(requirement["fallbackAttempts"]), 2)
        self.assertEqual(requirement["fallbackAttempts"][0]["providerId"], "PROV-A")
        self.assertFalse(requirement["fallbackAttempts"][0]["success"])
        self.assertEqual(requirement["fallbackAttempts"][1]["providerId"], "PROV-B")
        self.assertTrue(requirement["fallbackAttempts"][1]["success"])
        # Exactly one citizen-facing "Auto-Fill" attempt/mutation happened,
        # regardless of how many providers the cascade tried internally.
        self.assertEqual(requirement["attempts"], 1)

    # 3. Primary fails -> fallback fails -> next eligible provider succeeds.
    def test_cascades_through_multiple_fallbacks_until_one_succeeds(self):
        application = self._apply("CITIZEN_FB_003")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _failure(), _success(provider_id="PROV-C")]), \
             patch.object(retry_policy, "find_fallback_candidate", side_effect=[PROVIDER_B, PROVIDER_C]):
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_003")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertEqual(requirement["providerId"], "PROV-C")
        self.assertEqual(len(requirement["fallbackAttempts"]), 3)
        self.assertEqual([a["providerId"] for a in requirement["fallbackAttempts"]], ["PROV-A", "PROV-B", "PROV-C"])

    # 4. No eligible fallback -> existing retry/action-required behavior preserved.
    def test_no_eligible_fallback_falls_through_to_existing_retry_behavior(self):
        application = self._apply("CITIZEN_FB_004")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure()), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=None):
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_004")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertEqual(requirement["status"], "WAITING")
        self.assertEqual(len(requirement["fallbackAttempts"]), 1)

    # 5. A provider already tried in this cascade is not selected again.
    def test_failed_provider_is_excluded_from_reselection_within_the_same_cascade(self):
        application = self._apply("CITIZEN_FB_005")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _success()]), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=PROVIDER_B) as mock_fallback:
            self._fulfill(application["appId"], code, "CITIZEN_FB_005")
        mock_fallback.assert_called_once()
        _, kwargs = mock_fallback.call_args
        self.assertIn("PROV-A", kwargs["exclude_provider_ids"])

    # 6. Successful fallback does not create a duplicate fulfillment/document.
    def test_successful_fallback_creates_exactly_one_document(self):
        from app.core.persistence import get_document
        application = self._apply("CITIZEN_FB_006")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        # documents.provider_id has a foreign key to the real providers
        # table, so the fallback candidate here must be a real registered
        # provider, not a synthetic PROV-* test id.
        fallback = {**PROVIDER_B, "providerId": "REVENUE-DEPARTMENT"}
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _success(provider_id="REVENUE-DEPARTMENT")]), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=fallback):
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_006")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertEqual(requirement["status"], "VALIDATED")
        # requirement_fulfillment never writes documentId onto the
        # requirement dict itself for the Auto-Fill path (only manual
        # upload does) -- the document lives at the deterministic id
        # DOC-{appId}-{code}, exactly like test_requirement_resilience.py
        # already looks it up.
        document = get_document(f"DOC-{application['appId']}-{code}")
        self.assertIsNotNone(document)
        self.assertEqual(document["providerId"], "REVENUE-DEPARTMENT")

    # 7. Successful fallback creates correct audit lineage.
    def test_fallback_cascade_produces_audit_lineage_for_each_attempt(self):
        application = self._apply("CITIZEN_FB_007")
        code = application["requirements"][0]["requirementCode"]
        before = len(audit_bus.entries)
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _success()]), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=PROVIDER_B):
            self._fulfill(application["appId"], code, "CITIZEN_FB_007")
        new_entries = audit_bus.entries[before:]
        actions = [entry["action"] for entry in new_entries]
        self.assertIn("SELECT", actions)
        self.assertIn("FAIL", actions)
        self.assertIn("FALLBACK_SELECTED", actions)
        self.assertIn("RETRIEVED", actions)
        correlated = [entry for entry in new_entries if entry["correlationId"] == application["appId"]]
        self.assertEqual(len(correlated), len(new_entries), "every cascade audit entry must correlate to the application")

    # 8. Citizen-facing response never leaks provider/fallback internals.
    def test_citizen_facing_response_never_exposes_provider_or_fallback_details(self):
        from app.api.citizen_routes import AutoFillDecision, auto_fill_requirement
        application = self._apply("CITIZEN_FB_008")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=[_failure(), _success()]), \
             patch.object(retry_policy, "find_fallback_candidate", return_value=PROVIDER_B):
            safe_result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_FB_008"))
        safe_requirement = next(item for item in safe_result["requirements"] if item["requirementCode"] == code)
        self.assertNotIn("providerId", safe_requirement)
        self.assertNotIn("fallbackAttempts", safe_requirement)
        self.assertNotIn("isFallback", safe_requirement)
        self.assertIn(safe_requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)

    # 9. Non-retryable failure never triggers a fallback attempt (policy-driven, not hardcoded).
    def test_non_retryable_failure_never_triggers_fallback(self):
        application = self._apply("CITIZEN_FB_009")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=PROVIDER_A), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure(category="VALIDATION_ERROR", retryable=False)), \
             patch.object(retry_policy, "find_fallback_candidate") as mock_fallback:
            result = self._fulfill(application["appId"], code, "CITIZEN_FB_009")
        requirement = requirement_fulfillment.find_requirement(result, code)
        self.assertEqual(requirement["status"], "FAILED")
        self.assertEqual(len(requirement["fallbackAttempts"]), 1)
        mock_fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
