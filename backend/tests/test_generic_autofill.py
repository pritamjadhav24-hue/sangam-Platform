"""Generic, registry-driven Auto-Fill across independent department APIs.

Auto-Fill is not tied to any department: every department API offers the same
canonical lookup contract (app.department_api.resolution), the department
adapter speaks only that contract over HTTP, discovery walks the provider
registry, and SANGAM re-checks every returned identity before using it.

The department APIs run for real (uvicorn, plain urllib) against *temporary*
sandbox databases: the module refuses to run unless SANDBOX_DATA_DIR points
at a throwaway directory, so no developer or live department database is
ever touched.
"""
from __future__ import annotations

import importlib
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import uvicorn
from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.engine import adapters, requirement_fulfillment
from app.engine.adapters import AdapterResult, DepartmentSandboxAPIAdapter, resolve_path_for
from app.seeds.demo_citizens import DEMO_CITIZENS

TEST_PORT = 18197
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
CORE_DEPARTMENTS = ("revenue", "education", "social_welfare", "municipal_health", "transport")
CITIZENS = {citizen["citizenId"]: citizen for citizen in DEMO_CITIZENS}


def identity(citizen_id: str, **overrides) -> dict:
    citizen = CITIZENS[citizen_id]
    return {**{"name": citizen["name"], "dob": citizen["dob"], "phone": citizen.get("phone")}, **overrides}


def adapter(http_path: str, provider_id: str = "TEST-PROVIDER") -> DepartmentSandboxAPIAdapter:
    return DepartmentSandboxAPIAdapter(provider_id, provider_id=provider_id, config={
        "providerId": provider_id, "httpPath": http_path, "endpointRef": "SANGAM_TEST_DEPARTMENT_API", "maxAttempts": 1, "timeoutSeconds": 5,
    })


_server = None
_thread = None


def _sandbox_is_throwaway(engine) -> bool:
    data_dir = os.getenv("SANDBOX_DATA_DIR")
    url = str(engine.url)
    if not data_dir or not url.startswith("sqlite:///"):
        return False
    temp_root = Path(tempfile.gettempdir()).resolve()
    database = Path(url[len("sqlite:///"):]).resolve()
    return Path(data_dir).resolve() in database.parents and temp_root in database.parents


def setUpModule():
    global _server, _thread
    from app.sandbox.common import session_scope
    from app.sandbox.registry import SANDBOXES_BY_KEY
    for key in CORE_DEPARTMENTS:
        spec = SANDBOXES_BY_KEY[key]
        models = importlib.import_module(spec.models_module)
        if not _sandbox_is_throwaway(models.ENGINE):
            raise unittest.SkipTest("department sandboxes are not throwaway databases (run through the throwaway test runner)")
        models.Base.metadata.create_all(models.ENGINE)
        with session_scope(models.ENGINE) as session:
            importlib.import_module(spec.seed_module).seed_demo(session)  # idempotent
    from app.department_api.main import app
    _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="error"))
    _thread = threading.Thread(target=_server.run, daemon=True)
    _thread.start()
    for _ in range(200):
        if getattr(_server, "started", False):
            break
        time.sleep(0.05)


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _thread.join(timeout=5)


class DepartmentAutoFillTests(unittest.TestCase):
    """1-5 and 8-9: the same code path serves every department. The SANGAM
    citizen id deliberately differs from anything the departments hold, so
    each department must find the person itself (entity resolution)."""

    SANGAM_ID = "SANGAM-CIT-NOT-HELD-BY-ANY-DEPARTMENT"

    def setUp(self):
        self.env = patch.dict(os.environ, {"SANGAM_TEST_DEPARTMENT_API": BASE_URL})
        self.env.start()
        for key in [key for key in os.environ if key.startswith("DEPARTMENT_API_URL_")]:
            os.environ.pop(key)

    def tearDown(self):
        self.env.stop()

    def _autofill(self, http_path: str, citizen_id: str, **identity_overrides) -> tuple[AdapterResult, dict]:
        """Retrieve through the adapter, then SANGAM's identity check and the
        requirement update -- exactly what fulfill_requirement does."""
        result = adapter(http_path).retrieve({"citizenId": self.SANGAM_ID, "identity": identity(citizen_id, **identity_overrides)})
        requirement = {"code": "TEST_REQUIREMENT", "status": "NOT_PROVIDED"}
        with patch("app.engine.entity_resolution.citizen_identity", return_value={"citizenId": self.SANGAM_ID, **identity(citizen_id, **identity_overrides)}):
            requirement_fulfillment._attach_identity_match(result, self.SANGAM_ID)
        with patch("app.engine.departments.provider_department", return_value="TEST"):
            requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        return result, requirement

    def _assert_auto_filled(self, http_path, citizen_id, expected_field):
        result, requirement = self._autofill(http_path, citizen_id)
        self.assertTrue(result.success, result.metadata)
        self.assertIn(expected_field, result.record["raw"])
        self.assertEqual(result.record["departmentMatch"]["method"], "DEMOGRAPHIC")
        self.assertEqual(requirement["identityMatch"]["decision"], "AUTO_ACCEPT")
        self.assertIn(requirement["status"], {"VALIDATED", "RETRIEVED", "REJECTED"})
        self.assertNotEqual(requirement.get("errorCategory"), "IDENTITY_UNCONFIRMED")
        return result, requirement

    def test_01_income_from_revenue(self):
        self._assert_auto_filled("/departments/revenue/income-certificates/{citizenRef}", "DEMO-CIT-001", "annual_income")

    def test_02_marksheet_from_education(self):
        self._assert_auto_filled("/departments/education/academic-records/{citizenRef}", "DEMO-CIT-001", "marks_percentage")

    def test_03_caste_certificate_from_welfare(self):
        self._assert_auto_filled("/departments/social-welfare/caste-certificates/{citizenRef}", "DEMO-CIT-001", "caste_category")

    def test_04_health_record_from_health(self):
        self._assert_auto_filled("/departments/municipal-health/immunization-records/{citizenRef}", "DEMO-CIT-003", "doses")

    def test_05_transport_record_from_transport(self):
        self._assert_auto_filled("/departments/transport/driving-licences/{citizenRef}", "DEMO-CIT-003", "licence_class")

    def test_08_differently_kept_identity_is_resolved(self):
        # Welfare keeps "Kumar Rahul" / "09876543210"; SANGAM says "Rahul Kumar" / "+91-9876543210".
        result, requirement = self._assert_auto_filled("/departments/social-welfare/bank-linkages/{citizenRef}", "DEMO-CIT-001", "bank_name")
        self.assertIn(requirement["identityMatch"]["matchCategory"], {"STRONG", "EXACT"})

    def test_09_wrong_citizen_gets_no_record(self):
        result, requirement = self._autofill("/departments/revenue/income-certificates/{citizenRef}", "DEMO-CIT-001",
                                             name="Somebody Else", dob="1970-01-01", phone="+91-9000000009")
        self.assertFalse(result.success)
        self.assertTrue(result.metadata.get("recordNotFound"))
        self.assertEqual(requirement["status"], "FAILED")
        self.assertNotIn("canonical", requirement)

    def test_10_low_confidence_match_is_not_auto_filled(self):
        # Same date of birth and phone, a different name: the department may
        # offer a candidate, but SANGAM's confidence is too low to attach it.
        result, requirement = self._autofill("/departments/revenue/income-certificates/{citizenRef}", "DEMO-CIT-001", name="Arjun Patil")
        self.assertTrue(result.success)
        self.assertEqual(requirement["status"], "ACTION_REQUIRED")
        self.assertEqual(requirement["errorCategory"], "IDENTITY_UNCONFIRMED")
        self.assertNotIn("canonical", requirement)
        self.assertNotIn("provenance", requirement)

    def test_ambiguous_lookup_answers_no_record_rather_than_guessing(self):
        # Two different people with the same name and date of birth: the
        # department must not pick one.
        from app.department_api.resolution import CanonicalLookup, PersonIndex, find_person

        class Base(DeclarativeBase):
            pass

        class Person(Base):
            __tablename__ = "people"
            person_id: Mapped[str] = mapped_column(String, primary_key=True)
            citizen_ref: Mapped[str] = mapped_column(String)
            name: Mapped[str] = mapped_column(String)
            dob: Mapped[str] = mapped_column(String)

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        index = PersonIndex(Person, id_field="person_id", name_field="name", dob_field="dob", identifier_names=("person_id",))
        with Session(engine) as session:
            session.add_all([Person(person_id="P1", citizen_ref="R1", name="Asha Rao", dob="2000-01-01"),
                             Person(person_id="P2", citizen_ref="R2", name="ASHA RAO", dob="01-01-2000")])
            session.commit()
            self.assertEqual(find_person(session, index, CanonicalLookup(name="Asha Rao", dob="2000-01-01")), (None, "AMBIGUOUS"))
            person, method = find_person(session, index, CanonicalLookup(name="Asha Rao", dob="2000-01-01", identifiers={"person_id": "P2"}))
            self.assertEqual((person.person_id, method), ("P2", "DEPARTMENT_IDENTIFIER"))
            self.assertEqual(find_person(session, index, CanonicalLookup(name="Asha Rao"))[1], "INSUFFICIENT_IDENTITY")

    def test_15_a_newly_registered_capability_needs_no_auto_fill_code(self):
        # Education enrollments has never been an Auto-Fill capability. A
        # registry entry (record path) is all it takes: the contract path is
        # derived by convention and the same adapter serves it.
        path = "/departments/education/enrollments/{citizenRef}"
        self.assertEqual(resolve_path_for({"httpPath": path}), "/departments/education/resolve/enrollments")
        self._assert_auto_filled(path, "DEMO-CIT-001", "enrolled")

    def test_department_without_the_contract_still_answers_through_its_original_lookup(self):
        result = DepartmentSandboxAPIAdapter("Legacy", provider_id="LEGACY", config={
            "httpPath": "/departments/revenue/income-certificates/{citizenRef}", "endpointRef": "SANGAM_TEST_DEPARTMENT_API",
            "maxAttempts": 1, "resolvePath": "/departments/revenue/no-such-contract"}).retrieve({"citizenId": "DEMO-CIT-001", "identity": {}})
        self.assertTrue(result.success)


class ResilienceTests(unittest.TestCase):
    """6, 7, 11, 12: fallback, no provider, API error, database unavailable."""

    REVENUE = {"requirementCode": "INCOME_PROOF", "providerId": "REV", "provider": "Revenue", "serviceId": "S-REV", "priority": 10, "healthStatus": "AVAILABLE", "authorization": {"role": "AUTHORITATIVE"}}
    WELFARE = {"requirementCode": "INCOME_PROOF", "providerId": "SW", "provider": "Welfare", "serviceId": "S-SW", "priority": 30, "healthStatus": "AVAILABLE", "authorization": {"role": "AUTHORIZED_FALLBACK"}}

    def _cascade(self, answers: dict, registry: list, first):
        def call(service_id, *_args, **_kwargs):
            return answers[service_id]

        def next_candidate(_code, exclude_provider_ids=()):
            return next((item for item in registry if item["providerId"] not in exclude_provider_ids and item["healthStatus"] == "AVAILABLE"), None)

        with patch.object(requirement_fulfillment, "health_for_selection", return_value=[]), \
             patch.object(requirement_fulfillment, "select_dependency_provider", return_value=first), \
             patch.object(requirement_fulfillment, "dependency_registry", return_value=registry), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=call), \
             patch.object(requirement_fulfillment.retry_policy, "find_fallback_candidate", side_effect=next_candidate), \
             patch.object(requirement_fulfillment, "audit_bus"):
            return requirement_fulfillment._discover_and_retrieve("INCOME_PROOF", "C1", "APP-1", "APP-1", "CONSENT-1")

    @staticmethod
    def _no_record():
        return AdapterResult(None, success=False, error_category="VALIDATION_ERROR", metadata={"recordNotFound": True})

    def test_06_no_record_in_one_department_asks_the_next_registered_provider(self):
        result, log = self._cascade({"S-REV": self._no_record(), "S-SW": AdapterResult({"id": "SW-1"}, success=True)},
                                    [self.REVENUE, self.WELFARE], self.REVENUE)
        self.assertTrue(result.success)
        self.assertEqual([(entry["providerId"], entry["success"], entry.get("recordNotFound", False)) for entry in log],
                         [("REV", False, True), ("SW", True, False)])

    def test_06_unavailable_primary_falls_back(self):
        down = dict(self.REVENUE, healthStatus="UNAVAILABLE")
        result, log = self._cascade({"S-SW": AdapterResult({"id": "SW-1"}, success=True)}, [down, self.WELFARE], self.WELFARE)
        self.assertTrue(result.success)
        self.assertEqual([entry["providerId"] for entry in log], ["REV", "SW"])

    def test_07_no_record_anywhere_leaves_manual_upload(self):
        result, _ = self._cascade({"S-REV": self._no_record(), "S-SW": self._no_record()}, [self.REVENUE, self.WELFARE], self.REVENUE)
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        from app.api.citizen_routes import NO_RECORD_MESSAGE, _requirement_user_action
        self.assertEqual(requirement["status"], "FAILED")
        self.assertEqual(_requirement_user_action(requirement), NO_RECORD_MESSAGE)
        self.assertIn("connected departments", NO_RECORD_MESSAGE)

    def test_07_no_registered_provider_fails_safely(self):
        result, log = self._cascade({}, [], None)
        self.assertFalse(result.success)
        self.assertEqual(log, [])
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        self.assertEqual(requirement["status"], "FAILED")

    def test_11_department_api_error_is_contained_and_retryable(self):
        with patch.dict(os.environ, {"SANGAM_TEST_DEPARTMENT_API": "http://127.0.0.1:9"}):
            result = adapter("/departments/revenue/income-certificates/{citizenRef}").retrieve({"citizenId": "C1", "identity": {}})
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        requirement = {"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}
        requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        self.assertEqual(requirement["status"], "WAITING")

    def test_12_department_database_unavailable_is_a_retryable_upstream_error(self):
        from app.department_api.common import department_health
        from sqlalchemy import create_engine
        response = department_health(create_engine("postgresql+psycopg://nobody@127.0.0.1:9/none", connect_args={"connect_timeout": 1}), "Test Dept")
        self.assertEqual(response.status_code, 503)

        def fail(*_args, **_kwargs):
            raise HTTPError("http://dept", 503, "Service Unavailable", {}, None)

        with patch.object(DepartmentSandboxAPIAdapter, "_send", side_effect=fail), patch.dict(os.environ, {"SANGAM_TEST_DEPARTMENT_API": BASE_URL}):
            result = adapter("/departments/revenue/income-certificates/{citizenRef}").retrieve({"citizenId": "C1", "identity": {}})
        self.assertEqual(result.error_category, "UPSTREAM_ERROR")
        self.assertTrue(result.retryable)


class ConsentAndProvenanceTests(unittest.TestCase):
    """13-14: no consent, no retrieval; provenance kept, and kept citizen-safe."""

    def test_13_without_consent_no_department_is_called(self):
        from app.engine.consent_manager import ConsentAuthorizationError
        application = {"appId": "APP-NO-CONSENT", "serviceId": "SCH-MH-2026", "requirements": [{"code": "INCOME_PROOF", "status": "NOT_PROVIDED"}]}
        with patch.object(requirement_fulfillment, "_discover_and_retrieve") as discover, \
             patch.object(requirement_fulfillment, "execute_with_persisted_authorization", side_effect=ConsentAuthorizationError("Consent is missing")):
            with self.assertRaises(ConsentAuthorizationError):
                requirement_fulfillment.fulfill_requirement(application, "INCOME_PROOF", "C1", "CONSENT-MISSING")
        discover.assert_not_called()

    def test_14_provenance_is_recorded_and_the_citizen_view_stays_minimal(self):
        record = {"id": "EDU-REC-9", "raw": {"marks_percentage": 78.4}, "canonical": {"academicPercentage": 78.4},
                  "departmentMatch": {"method": "DEMOGRAPHIC", "departmentPersonId": "STU-9182"}}
        result = AdapterResult(record, success=True, metadata={"providerId": "EDUCATION-SANDBOX-ACADEMIC", "identityMatch": {
            "decision": "AUTO_ACCEPT", "status": "MATCH", "confidenceLevel": "HIGH", "score": 0.93, "matchCategory": "STRONG"}})
        requirement = {"code": "ACADEMIC_RECORD", "status": "NOT_PROVIDED", "isFallback": False}
        with patch("app.engine.departments.provider_department", return_value="EDUCATION"):
            requirement_fulfillment._apply_outcome_to_requirement(requirement, result)
        provenance = requirement["provenance"]
        self.assertEqual({key: provenance[key] for key in ("sourceDepartment", "providerId", "sourceRecordId", "verificationMethod", "recordKind", "matchCategory", "confidence", "departmentMatchMethod")},
                         {"sourceDepartment": "EDUCATION", "providerId": "EDUCATION-SANDBOX-ACADEMIC", "sourceRecordId": "EDU-REC-9",
                          "verificationMethod": "DEPARTMENT_API_RECORD", "recordKind": "STRUCTURED_RECORD", "matchCategory": "STRONG",
                          "confidence": 0.93, "departmentMatchMethod": "DEMOGRAPHIC"})
        self.assertTrue(provenance["verifiedAt"])
        from app.api.citizen_routes import _verified_source
        requirement["status"] = "VALIDATED"
        view = _verified_source(requirement)
        self.assertEqual(view["source"], "Education Department")
        self.assertFalse(view["alternateSource"])
        self.assertFalse({"providerId", "provenance", "sourceRecordId", "departmentMatchMethod"} & set(view))

    def test_contract_is_derived_from_the_registry_rows(self):
        from app.core.persistence import ProviderCapabilityRow, ProviderRow, SchemaMappingRow, capability_contract
        provider = ProviderRow(provider_id="PENSION-API", name="Pensions", adapter_type="Department Sandbox API",
                               payload={"httpPath": "/departments/pensions/pension-orders/{citizenRef}"})
        capability = ProviderCapabilityRow(capability_id="PENSION-API:PENSION_ORDER", provider_id="PENSION-API", capability_code="PENSION_ORDER", payload={"priority": 10})
        mapping = SchemaMappingRow(mapping_id="m", provider_id="PENSION-API", department_field="order_no", canonical_field="pensionOrderNumber", payload={})
        with patch("app.engine.artifact_retrieval.is_document_requirement", return_value=False):
            contract = capability_contract(provider, capability, [mapping], ["OTHER-API"])
        self.assertEqual(contract["endpoint"], "/departments/pensions/resolve/pension-orders")
        self.assertEqual(contract["operation"], "RESOLVE_RECORD")
        self.assertEqual(contract["responseSchema"], ["pensionOrderNumber"])
        self.assertEqual(contract["fallbackProviders"], ["OTHER-API"])
        self.assertIn("dob", contract["supportedIdentifiers"])


if __name__ == "__main__":
    unittest.main()
