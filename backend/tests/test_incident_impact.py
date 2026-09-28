"""Provider incident impact (app.core.admin_insights.incident_impacts):
incident -> provider operation -> scheme requirement -> application ->
citizen, with unique-citizen counting and fallback/recovery states."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.core.admin_insights import incident_impacts
from app.core.persistence import ApplicationRow, ProviderIncidentRow, Session, engine, seed_catalog
from app.engine.requirement_fulfillment import _apply_outcome
from app.engine.adapters import AdapterResult

PRIMARY = {"providerId": "REVENUE-DEPARTMENT", "provider": "Revenue Department"}
FALLBACK = {"providerId": "REVENUE-SANDBOX-INCOME", "provider": "Revenue Sandbox API - Income Certificates"}
NOW = datetime.now(timezone.utc)
DETECTED, RESOLVED = NOW - timedelta(hours=2), NOW - timedelta(hours=1)
DURING, BEFORE = (NOW - timedelta(minutes=90)).isoformat(), (NOW - timedelta(hours=5)).isoformat()


def _op(at, outcome, *attempts):
    return {"at": at, "outcome": outcome, "attempts": list(attempts)}


def _failed(provider=PRIMARY, skipped=False):
    return {**provider, "success": False, "skipped": skipped, "errorCategory": "UPSTREAM_UNAVAILABLE"}


def _ok(provider):
    return {**provider, "success": True, "skipped": False, "errorCategory": None}


def _requirement(code, status, history=(), **extra):
    return {"code": code, "label": code.replace("_", " ").title(), "status": status, "providerHistory": list(history), **extra}


APPS = {
    # Same citizen, two blocked applications -> counted once as a citizen.
    "APP-IMPACT-1": ("CITIZEN_IMP_A", "IN_PROGRESS", "SCH-MH-2026", [_requirement("INCOME_PROOF", "WAITING", [_op(DURING, "WAITING", _failed())], errorCategory="UPSTREAM_UNAVAILABLE")]),
    "APP-IMPACT-2": ("CITIZEN_IMP_A", "IN_PROGRESS", "SCH-MH-2026", [_requirement("DOMICILE_PROOF", "ACTION_REQUIRED", [_op(DURING, "ACTION_REQUIRED", _failed())])]),
    # Primary skipped, fallback served it in the same operation.
    "APP-IMPACT-3": ("CITIZEN_IMP_B", "IN_PROGRESS", "SCH-MH-2026", [_requirement("INCOME_PROOF", "VALIDATED", [_op(DURING, "VALIDATED", _failed(skipped=True), _ok(FALLBACK))], providerId=FALLBACK["providerId"])]),
    # Blocked during the outage, then fulfilled by the same provider later.
    "APP-IMPACT-4": ("CITIZEN_IMP_C", "SUBMITTED", "SCH-MH-2026", [_requirement("INCOME_PROOF", "VALIDATED", [_op(DURING, "WAITING", _failed()), _op(NOW.isoformat(), "VALIDATED", _ok(PRIMARY))], providerId=PRIMARY["providerId"])]),
    # Not affected: failure outside the window, and a requirement the provider does not serve.
    "APP-IMPACT-5": ("CITIZEN_IMP_D", "IN_PROGRESS", "SCH-MH-2026", [_requirement("INCOME_PROOF", "WAITING", [_op(BEFORE, "WAITING", _failed())]),
                                                                       _requirement("CASTE_PROOF", "WAITING", [_op(DURING, "WAITING", _failed({"providerId": "SOCIAL-WELFARE-DEPARTMENT", "provider": "Social Welfare Department"}))])]),
    # Not affected: nothing attempted and the incident is resolved.
    "APP-IMPACT-6": ("CITIZEN_IMP_E", "IN_PROGRESS", "SCH-MH-2026", [_requirement("INCOME_PROOF", "NOT_PROVIDED")]),
}


def setUpModule():
    with patch.dict(os.environ, {"SANGAM_SEED_CATALOG": "true"}):
        seed_catalog()


class IncidentImpactTests(unittest.TestCase):
    RESOLVED_ID, OPEN_ID = "INC-TEST-IMPACT-RESOLVED", "INC-TEST-IMPACT-OPEN"

    def setUp(self):
        with Session(engine) as session:
            for app_id, (citizen, status, scheme, requirements) in APPS.items():
                session.add(ApplicationRow(app_id=app_id, citizen_id=citizen, status=status,
                                           payload={"appId": app_id, "citizenId": citizen, "status": status, "serviceId": scheme, "requirements": requirements}))
            session.add(ProviderIncidentRow(incident_id=self.RESOLVED_ID, provider_system="Revenue Department", status="RESOLVED",
                                            detected_at=DETECTED, resolved_at=RESOLVED, payload={}))
            session.commit()

    def tearDown(self):
        with Session(engine) as session:
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(list(APPS))).delete(synchronize_session=False)
            session.query(ProviderIncidentRow).filter(ProviderIncidentRow.incident_id.in_([self.RESOLVED_ID, self.OPEN_ID])).delete(synchronize_session=False)
            session.commit()

    def _impact(self, incident_id):
        return incident_impacts([incident_id], include_applications=True)[incident_id]

    def test_affected_applications_citizens_and_schemes(self):
        impact = self._impact(self.RESOLVED_ID)
        self.assertEqual({app["appId"] for app in impact["applications"]}, {"APP-IMPACT-1", "APP-IMPACT-2", "APP-IMPACT-3", "APP-IMPACT-4"})
        self.assertEqual(impact["affectedApplicationsTotal"], 4)
        self.assertEqual(impact["affectedCitizens"], 3, "CITIZEN_IMP_A has two applications but is one citizen")
        self.assertEqual(impact["affectedSchemes"], ["Post-Matric Higher Education Scholarship"])

    def test_blocked_retry_fallback_and_recovery_counts(self):
        impact = self._impact(self.RESOLVED_ID)
        self.assertEqual(impact["blockedOperations"], 2)
        self.assertEqual(impact["pendingRetries"], 1)
        self.assertEqual(impact["successfulFallbacks"], 1)
        self.assertEqual(impact["recoveredApplications"], 1)
        by_app = {app["appId"]: app for app in impact["applications"]}
        self.assertEqual(by_app["APP-IMPACT-1"]["requirements"][0]["state"], "RETRY_PENDING")
        self.assertIn("Income Proof", by_app["APP-IMPACT-1"]["blockedStage"])
        self.assertEqual(by_app["APP-IMPACT-3"]["requirements"][0]["resolvedBy"], FALLBACK["provider"])
        self.assertEqual(by_app["APP-IMPACT-4"]["requirements"][0]["resolvedBy"], "Same provider after recovery")

    def test_citizen_upload_after_blocking_counts_as_recovered(self):
        with Session(engine) as session:
            row = session.get(ApplicationRow, "APP-IMPACT-2")
            payload = dict(row.payload)
            payload["requirements"] = [{**payload["requirements"][0], "status": "VALIDATED", "documentId": "DOC-X"}]
            row.payload = payload
            session.commit()
        impact = self._impact(self.RESOLVED_ID)
        self.assertEqual(impact["recoveredApplications"], 2)
        self.assertEqual(impact["blockedOperations"], 1)

    def test_open_incident_blocks_unattempted_requirements_without_an_alternative(self):
        with Session(engine) as session:
            session.add(ProviderIncidentRow(incident_id=self.OPEN_ID, provider_system="Revenue Department", status="OPEN",
                                            detected_at=NOW - timedelta(minutes=5), payload={}))
            session.commit()
        down = [{"requirementCode": "INCOME_PROOF", **PRIMARY, "healthStatus": "UNAVAILABLE"}, {"requirementCode": "DOMICILE_PROOF", **PRIMARY, "healthStatus": "UNAVAILABLE"}]
        with patch("app.engine.registry.dependency_registry", return_value=down), patch("app.engine.adapters.integration_health", return_value=[]):
            impact = self._impact(self.OPEN_ID)
        self.assertIn("APP-IMPACT-6", {app["appId"] for app in impact["applications"]})
        state = next(app for app in impact["applications"] if app["appId"] == "APP-IMPACT-6")["requirements"][0]["state"]
        self.assertEqual(state, "AWAITING_PROVIDER")
        self.assertNotIn("APP-IMPACT-4", {app["appId"] for app in impact["applications"]}, "a submitted application is not blocked")

        healthy_alternative = down + [{"requirementCode": "INCOME_PROOF", **FALLBACK, "healthStatus": "AVAILABLE"}]
        with patch("app.engine.registry.dependency_registry", return_value=healthy_alternative), patch("app.engine.adapters.integration_health", return_value=[]):
            impact = self._impact(self.OPEN_ID)
        self.assertNotIn("APP-IMPACT-6", {app["appId"] for app in impact["applications"]}, "a healthy fallback exists, so it is not blocked")


class ProviderHistoryRecordingTests(unittest.TestCase):
    def test_each_operation_is_recorded_with_time_attempts_and_outcome(self):
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        failure = AdapterResult(None, success=False, error_category="UPSTREAM_UNAVAILABLE", retryable=True)
        _apply_outcome(requirement, failure, [{**PRIMARY, "isFallback": False, "success": False, "skipped": True, "errorCategory": "UPSTREAM_UNAVAILABLE"}])
        success = AdapterResult({"id": "R1", "canonical": {"incomeAmount": 1}}, success=True, metadata={"providerId": PRIMARY["providerId"]})
        _apply_outcome(requirement, success, [{**PRIMARY, "isFallback": False, "success": True, "errorCategory": None}])
        history = requirement["providerHistory"]
        self.assertEqual([op["outcome"] for op in history], ["WAITING", "VALIDATED"])
        self.assertTrue(history[0]["attempts"][0]["skipped"])
        self.assertTrue(all(op["at"] for op in history))


if __name__ == "__main__":
    unittest.main()


# Remove every runtime row this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())
