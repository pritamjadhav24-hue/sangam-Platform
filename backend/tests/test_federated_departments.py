"""Federated department architecture: entity resolution across differently
kept department records, the fallback cascade's outage semantics, identity
gating of department records, department-level health, and the explicit
public-demo gate. Pure unit tests (no department service, no registry writes).
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.engine import adapters, requirement_fulfillment
from app.engine.adapters import AdapterResult
from app.engine.entity_resolution import match_department_record, normalize_address

CITIZEN = {"name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "address": "12 MG Road, Andheri West, Mumbai 400058"}


class DepartmentEntityResolutionTests(unittest.TestCase):
    def test_address_abbreviations_normalize_to_the_same_address(self):
        self.assertEqual(normalize_address("12, Mahatma Gandhi Rd., Andheri(W), Mumbai"), "12 mahatma gandhi road andheri west mumbai")
        self.assertEqual(normalize_address("12 MG Road, Andheri West, Mumbai"), "12 mahatma gandhi road andheri west mumbai")

    def test_same_person_kept_differently_by_three_departments_matches_with_high_confidence(self):
        records = [
            {"resident_name": "Rahul Kumar", "dob": "2005-06-15", "mobile": "+91 98765 43210", "address": "12 MG Road, Andheri West, Mumbai 400058"},
            {"student_name": "RAHUL KUMAR", "date_of_birth": "2005-06-15", "guardian_mobile": "9876543210"},
            {"name": "Kumar Rahul", "date_of_birth": "2005-06-15", "mobile": "09876543210", "address": "12, Mahatma Gandhi Rd., Andheri(W), Mumbai"},
        ]
        for raw in records:
            with self.subTest(raw=raw):
                result = match_department_record(CITIZEN, raw, "Department")
                self.assertEqual(result["decision"], "AUTO_ACCEPT")
                self.assertEqual(result["confidenceLevel"], "HIGH")

    def test_same_name_but_different_person_is_not_attached(self):
        result = match_department_record({"name": "Sachin More", "dob": "2003-07-09", "phone": "+91-9870001112"},
                                         {"student_name": "SACHIN MORE", "date_of_birth": "1999-01-30", "guardian_mobile": "9123400000"})
        self.assertNotEqual(result["decision"], "AUTO_ACCEPT")
        self.assertIn("name", result["matchedFields"])
        self.assertNotIn("date_of_birth", result["matchedFields"])

    def test_record_without_identity_fields_is_not_evaluated(self):
        self.assertIsNone(match_department_record(CITIZEN, {"annual_income": 320000}))


class IdentityGatingTests(unittest.TestCase):
    def _record(self):
        return {"id": "REV-1", "status": "ISSUED", "raw": {"annual_income": 320000}, "canonical": {"incomeAmount": 320000}, "sourceSystem": "Revenue"}

    def test_unconfirmed_identity_keeps_the_requirement_open_and_attaches_nothing(self):
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        result = AdapterResult(self._record(), success=True, metadata={"providerId": "REVENUE-SANDBOX-INCOME",
                                                                         "identityMatch": {"decision": "UNRESOLVED", "status": "MISMATCH", "confidenceLevel": "LOW"}})
        requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        self.assertEqual(requirement["status"], "ACTION_REQUIRED")
        self.assertEqual(requirement["errorCategory"], "IDENTITY_UNCONFIRMED")
        self.assertNotIn("canonical", requirement)

    def test_confirmed_identity_records_the_verifying_department(self):
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        result = AdapterResult(self._record(), success=True, metadata={"providerId": "REVENUE-SANDBOX-INCOME",
                                                                         "identityMatch": {"decision": "AUTO_ACCEPT", "status": "MATCH", "confidenceLevel": "HIGH"}})
        with patch("app.engine.departments.provider_department", return_value="REVENUE"):
            requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        self.assertIn(requirement["status"], {"VALIDATED", "RETRIEVED"})
        self.assertEqual(requirement["sourceDepartment"], "REVENUE")
        self.assertTrue(requirement["verifiedAt"])


class FallbackCascadeOutageTests(unittest.TestCase):
    PRIMARY = {"requirementCode": "INCOME_PROOF", "providerId": "REV", "provider": "Revenue", "serviceId": "S-REV", "priority": 10, "healthStatus": "UNAVAILABLE", "authorization": {"role": "AUTHORITATIVE"}}
    FALLBACK = {"requirementCode": "INCOME_PROOF", "providerId": "SW", "provider": "Welfare", "serviceId": "S-SW", "priority": 30, "healthStatus": "AVAILABLE", "authorization": {"role": "AUTHORIZED_FALLBACK"}}

    def _run(self, fallback_result):
        with patch.object(requirement_fulfillment, "health_for_selection", return_value=[]), \
             patch.object(requirement_fulfillment, "select_dependency_provider", return_value=self.FALLBACK), \
             patch.object(requirement_fulfillment, "dependency_registry", return_value=[self.PRIMARY, self.FALLBACK]), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=fallback_result), \
             patch.object(requirement_fulfillment.retry_policy, "find_fallback_candidate", return_value=None), \
             patch.object(requirement_fulfillment, "audit_bus"):
            return requirement_fulfillment._discover_and_retrieve("INCOME_PROOF", "C1", "APP-1", "APP-1", "CONSENT-1")

    def test_fallback_provider_serves_the_requirement_when_the_primary_is_down(self):
        result, log = self._run(AdapterResult({"id": "SW-1"}, success=True))
        self.assertTrue(result.success)
        self.assertEqual([(entry["providerId"], entry.get("skipped", False), entry["success"]) for entry in log],
                         [("REV", True, False), ("SW", False, True)])

    def test_primary_down_and_fallback_without_a_record_means_temporarily_unavailable_not_no_record(self):
        result, _ = self._run(AdapterResult(None, success=False, error_category="VALIDATION_ERROR"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_category, "UPSTREAM_UNAVAILABLE")
        self.assertTrue(result.retryable)


class ProviderHealthTests(unittest.TestCase):
    def setUp(self):
        adapters._runtime_health.pop("Test Dept", None)

    def test_a_no_record_answer_never_degrades_a_department(self):
        adapters._record_runtime_failure("Test Dept", "VALIDATION_ERROR")
        self.assertNotIn("Test Dept", adapters._runtime_health)

    def test_degraded_is_temporary_and_cleared_by_a_later_success(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(adapters._recent_failure({"lastFailureAt": now.isoformat(), "errorCategory": "TIMEOUT"}))
        self.assertFalse(adapters._recent_failure({"lastFailureAt": (now - timedelta(seconds=adapters.DEGRADED_WINDOW_SECONDS + 5)).isoformat(), "errorCategory": "TIMEOUT"}))
        self.assertFalse(adapters._recent_failure({"lastFailureAt": now.isoformat(), "lastSuccessAt": (now + timedelta(seconds=1)).isoformat(), "errorCategory": "TIMEOUT"}))

    def test_only_a_dedicated_department_service_is_actively_probed(self):
        adapter = adapters.DepartmentSandboxAPIAdapter("Revenue", provider_id="REV", config={
            "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/revenue/income-certificates/{citizenRef}"})
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}), patch.object(adapters, "probe_department") as probe:
            os.environ.pop("DEPARTMENT_API_URL_REVENUE", None)
            self.assertEqual(adapter.health_check()["status"], "AVAILABLE")
            probe.assert_not_called()
        with patch.dict(os.environ, {"DEPARTMENT_API_URL_REVENUE": "http://127.0.0.1:1"}), \
             patch.object(adapters, "probe_department", return_value={"reachable": False, "latencyMs": 3.0, "checkedAt": "now"}):
            self.assertEqual(adapter.health_check()["status"], "UNAVAILABLE")

    def test_department_status_is_independent_per_department(self):
        from app.core.admin_insights import _department_status
        self.assertEqual(_department_status(["UNAVAILABLE", "UNAVAILABLE"]), "UNAVAILABLE")
        self.assertEqual(_department_status(["AVAILABLE", "UNAVAILABLE"]), "DEGRADED")
        self.assertEqual(_department_status(["AVAILABLE", "HEALTHY"]), "AVAILABLE")


class PublicDemoGateTests(unittest.TestCase):
    def test_public_demo_endpoints_are_off_unless_explicitly_enabled(self):
        from fastapi import HTTPException
        from app.api.auth_routes import DemoLogin, public_demo_accounts, public_demo_sign_in
        with patch.dict(os.environ, {"SANGAM_PUBLIC_DEMO": "false"}):
            for call in (lambda: public_demo_accounts(), lambda: public_demo_sign_in(DemoLogin(citizenId="DEMO-CIT-001"))):
                with self.assertRaises(HTTPException) as ctx:
                    call()
                self.assertEqual(ctx.exception.status_code, 404)

    def test_public_demo_sign_in_never_issues_a_token_for_a_non_demo_account(self):
        from fastapi import HTTPException
        from app.api.auth_routes import DemoLogin, public_demo_sign_in
        with patch.dict(os.environ, {"SANGAM_PUBLIC_DEMO": "true"}):
            for account in ("ADMIN_MH_01", "OFFICER_MH_01", "CITIZEN_001"):
                with self.assertRaises(HTTPException) as ctx:
                    public_demo_sign_in(DemoLogin(citizenId=account))
                self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
