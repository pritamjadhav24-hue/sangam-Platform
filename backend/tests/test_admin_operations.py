from __future__ import annotations

import unittest
from fastapi import HTTPException

from app.api.admin_routes import router, operations_overview, operations_incidents, list_admin_applications, get_admin_application_detail
from app.core.auth import require_roles
from app.core.persistence import (
    Session, engine, ApplicationRow, initialize, create_application,
)


class AdminOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_admin_role_enforced_on_all_new_operations_routes(self):
        guard = require_roles("ADMIN")
        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "CITIZEN_001", "role": "CITIZEN"})
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "OFFICER_MH_01", "role": "OFFICER"})
        self.assertEqual(ctx.exception.status_code, 403)

        admin = guard({"userId": "ADMIN_MH_01", "role": "ADMIN"})
        self.assertEqual(admin["role"], "ADMIN")

    def test_operations_overview_returns_expected_structure(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        overview = operations_overview(admin_user)
        
        self.assertIn("system", overview)
        self.assertIn("state", overview["system"])
        self.assertTrue(overview["system"]["postgresConnected"])
        self.assertEqual(overview["system"]["architecture"], "FEDERATED")
        self.assertIn("auditChainValid", overview["system"])

        self.assertIn("applications", overview)
        self.assertIn("total", overview["applications"])
        self.assertIn("automaticallyVerified", overview["applications"])
        self.assertIn("manuallyFulfilled", overview["applications"])
        self.assertIn("citizenActionRequired", overview["applications"])
        self.assertIn("officerReviewRequired", overview["applications"])
        self.assertIn("retryInProgress", overview["applications"])
        self.assertIn("requiringAttention", overview["applications"])

        self.assertIn("providers", overview)
        self.assertIn("registered", overview["providers"])
        self.assertIn("healthy", overview["providers"])
        self.assertIn("down", overview["providers"])
        self.assertIn("degraded", overview["providers"])

        self.assertIn("exceptions", overview)
        self.assertIn("activeProviderIncidents", overview["exceptions"])

        self.assertIn("jobs", overview)
        self.assertIn("counts", overview["jobs"])

    def test_operations_incidents_returns_list_and_lifecycle_is_tracked(self):
        from app.core.persistence import record_provider_health_transition, open_provider_incident_count
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = operations_incidents(admin_user)
        self.assertIn("incidents", res)
        self.assertIsInstance(res["incidents"], list)

        before = open_provider_incident_count()
        record_provider_health_transition("TEST_INCIDENT_PROVIDER", "Test Dept", "Test Service", "AVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")
        self.assertEqual(open_provider_incident_count(), before + 1)
        res_open = operations_incidents(admin_user)
        opened = next(i for i in res_open["incidents"] if i["providerSystem"] == "TEST_INCIDENT_PROVIDER")
        self.assertEqual(opened["status"], "OPEN")
        self.assertIsNone(opened["resolvedAt"])

        record_provider_health_transition("TEST_INCIDENT_PROVIDER", "Test Dept", "Test Service", "UNAVAILABLE", "AVAILABLE", None)
        self.assertEqual(open_provider_incident_count(), before)
        res_resolved = operations_incidents(admin_user)
        resolved = next(i for i in res_resolved["incidents"] if i["providerSystem"] == "TEST_INCIDENT_PROVIDER")
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertIsNotNone(resolved["resolvedAt"])

    def test_list_admin_applications_with_filters(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = list_admin_applications(status=None, search=None, limit=10, user=admin_user)
        self.assertIn("applications", res)
        self.assertIsInstance(res["applications"], list)

        if res["applications"]:
            first = res["applications"][0]
            self.assertIn("appId", first)
            self.assertIn("citizenId", first)
            self.assertIn("status", first)
            self.assertIn("requirementsCount", first)
            self.assertIn("fulfilledCount", first)

            # Test filter by exact appId
            search_res = list_admin_applications(status=None, search=first["appId"], limit=5, user=admin_user)
            self.assertTrue(any(a["appId"] == first["appId"] for a in search_res["applications"]))

    def test_get_admin_application_detail(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = list_admin_applications(status=None, search=None, limit=1, user=admin_user)
        if res["applications"]:
            app_id = res["applications"][0]["appId"]
            detail = get_admin_application_detail(app_id, user=admin_user)
            self.assertEqual(detail["appId"], app_id)
            self.assertIn("requirements", detail)
            self.assertIn("dependencies", detail)
            self.assertIn("jobs", detail)
            self.assertIn("auditEntries", detail)

            for req in detail["requirements"]:
                self.assertIn("fulfillmentMethod", req)
                self.assertIn("sourceCandidates", req)
                self.assertIn("isFallback", req)
                self.assertIn("primaryProvider", req)
                self.assertIn("primaryProviderIncident", req)
                self.assertIn("lineageSteps", req)
                self.assertIsInstance(req["lineageSteps"], list)
                self.assertGreaterEqual(len(req["lineageSteps"]), 1)
                self.assertIn("step", req["lineageSteps"][0])

        with self.assertRaises(HTTPException) as ctx:
            get_admin_application_detail("NONEXISTENT-APP-99999", user=admin_user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_requirement_lineage_labels_fallback_when_primary_provider_has_an_open_incident(self):
        from app.core.persistence import record_provider_health_transition
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = list_admin_applications(status=None, search=None, limit=20, user=admin_user)
        auto_fill_app_id = None
        for summary in res["applications"]:
            detail = get_admin_application_detail(summary["appId"], user=admin_user)
            if any(r["fulfillmentMethod"] == "AUTO_FILL" and r.get("sourceCandidates") for r in detail["requirements"]):
                auto_fill_app_id = summary["appId"]
                break
        if not auto_fill_app_id:
            self.skipTest("No seeded application has an Auto-Fill requirement with eligible provider candidates.")

        detail = get_admin_application_detail(auto_fill_app_id, user=admin_user)
        req = next(r for r in detail["requirements"] if r["fulfillmentMethod"] == "AUTO_FILL" and r.get("sourceCandidates"))
        primary_system = req["sourceCandidates"][0]["providerId"] or req["sourceCandidates"][0]["provider"]

        record_provider_health_transition(primary_system, primary_system, None, "AVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")
        try:
            detail_after = get_admin_application_detail(auto_fill_app_id, user=admin_user)
            req_after = next(r for r in detail_after["requirements"] if r["code"] == req["code"])
            if req_after.get("chosenProvider") not in (None, primary_system):
                # Only requirements still bound to the now-down primary
                # provider are expected to surface its open incident.
                self.assertIsNotNone(req_after["primaryProviderIncident"])
                self.assertEqual(req_after["primaryProviderIncident"]["providerSystem"], primary_system)
        finally:
            record_provider_health_transition(primary_system, primary_system, None, "UNAVAILABLE", "AVAILABLE", None)

    def test_admin_detail_reflects_a_real_fallback_cascade_end_to_end(self):
        from unittest.mock import patch
        from app.api.citizen_routes import ApplySchemeRequest, apply_to_scheme
        from app.engine.consent_manager import create_consent
        from app.core.persistence import get_application as get_application_raw
        from app.engine import requirement_fulfillment, retry_policy
        from types import SimpleNamespace

        def _user(citizen_id):
            return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test", "role": "CITIZEN"}

        application = apply_to_scheme(ApplySchemeRequest(schemeId="SCH-MH-2026"), SimpleNamespace(state=SimpleNamespace()), user=_user("CITIZEN_ADMIN_FB_001"))
        code = application["requirements"][0]["requirementCode"]
        app_snapshot = get_application_raw(application["appId"])
        receipt = create_consent(
            "CITIZEN_ADMIN_FB_001", True, attributes=[], service_id=app_snapshot.get("serviceId"),
            application_id=application["appId"], purpose=requirement_fulfillment.auto_fill_purpose(code),
        )
        primary = {"serviceId": "SVC-X", "providerId": "PROV-X", "provider": "Provider X", "priority": 10}
        fallback = {"serviceId": "SVC-Y", "providerId": "PROV-Y", "provider": "Provider Y", "priority": 20}
        from app.engine.adapters import AdapterResult
        try:
            with patch.object(requirement_fulfillment, "select_dependency_provider", return_value=primary), \
                 patch.object(requirement_fulfillment, "request_registered_service", side_effect=[
                     AdapterResult(None, success=False, error_category="TIMEOUT", retryable=True),
                     AdapterResult({"id": "REC-1", "canonical": {"value": "ok"}, "validUntil": None}, success=True, metadata={"providerId": "PROV-Y"}),
                 ]), \
                 patch.object(retry_policy, "find_fallback_candidate", return_value=fallback):
                requirement_fulfillment.fulfill_requirement(app_snapshot, code, "CITIZEN_ADMIN_FB_001", receipt["consentId"])

            admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
            detail = get_admin_application_detail(application["appId"], user=admin_user)
            req = next(r for r in detail["requirements"] if r["code"] == code)
            self.assertTrue(req["isFallback"])
            self.assertIn("Provider X", req["decisionReason"])
            self.assertIn("Provider Y", req["decisionReason"])
            step_labels = [s["step"] for s in req["lineageSteps"]]
            self.assertIn("Provider X (PRIMARY)", step_labels)
            self.assertIn("Provider Y (FALLBACK)", step_labels)
            self.assertIn("Attempt failed", step_labels)
            self.assertIn("Retrieval succeeded", step_labels)
        finally:
            with Session(engine) as session:
                session.query(ApplicationRow).filter(ApplicationRow.app_id == application["appId"]).delete(synchronize_session=False)
                session.commit()


if __name__ == "__main__":
    unittest.main()
