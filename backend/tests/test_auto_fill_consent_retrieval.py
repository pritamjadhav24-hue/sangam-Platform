"""Phase 6C: per-requirement Auto-Fill + consent + retrieval.

Route handlers are called directly as plain functions (this codebase's
established test convention -- see test_dynamic_application_form.py). Real
provider discovery/adapter calls are exercised through mocks here so these
tests run fast and deterministically; the REAL end-to-end pipeline (a live
department sandbox HTTP server, dynamic discovery, schema mapping,
validation) is covered separately in test_auto_fill_e2e.py, mirroring
test_dynamic_provider_e2e.py's existing heavier fixture.
"""
from __future__ import annotations

import ast
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.catalog_fixture import remove_test_vocabulary, seed_test_vocabulary
from app.api.citizen_routes import AutoFillDecision, apply_to_scheme, ApplySchemeRequest, auto_fill_requirement, get_citizen_application
from app.core.persistence import (
    CitizenNotificationRow,
    REQUIREMENT_CATALOG, ApplicationRow, ConsentRow, DocumentRow, RequirementCatalogRow,
    engine, get_document, seed_requirement_catalog,
)
from app.core.persistence import get_application as get_application_raw
from app.engine import requirement_fulfillment
from app.engine.adapters import AdapterResult
from app.engine.consent_manager import ConsentAuthorizationError
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace())


_VOCABULARY_ADDED: set[str] = set()


def setUpModule():
    _VOCABULARY_ADDED.update(seed_test_vocabulary())


def tearDownModule():
    remove_test_vocabulary(_VOCABULARY_ADDED)


def _success_result(record_id="REC-1", canonical=None, valid_until=None):
    # No providerId in metadata: requirement_fulfillment stores
    # adapter_result.provider_id straight onto the requirement, which then
    # flows into DocumentRow.provider_id (a real foreign key to the
    # providers table in production). Real provider calls always carry a
    # real, already-registered provider id; these unit tests mock the
    # adapter boundary itself, so they deliberately leave it unset (NULL is
    # a valid, FK-safe value) rather than fabricate an unregistered one.
    return AdapterResult(
        {"id": record_id, "canonical": canonical or {"value": "ok"}, "validUntil": valid_until},
        success=True,
    )


def _failure_result(category="UPSTREAM_UNAVAILABLE", retryable=True):
    return AdapterResult(None, success=False, error_category=category, retryable=retryable)


class AutoFillConsentRetrievalTests(unittest.TestCase):
    def setUp(self):
        self._created_app_ids: list[str] = []
        self._created_citizen_ids: list[str] = []

    def tearDown(self):
        with Session(engine) as session:
            if self._created_app_ids:
                session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
                session.query(CitizenNotificationRow).filter(CitizenNotificationRow.application_id.in_(self._created_app_ids)).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            if self._created_citizen_ids:
                session.query(ConsentRow).filter(ConsentRow.citizen_id.in_(self._created_citizen_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str = "SCH-MH-2026") -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._created_app_ids.append(application["appId"])
        self._created_citizen_ids.append(citizen_id)
        return application

    # ------------------------------------------------------------------
    # 1-2: consent integration
    # ------------------------------------------------------------------
    def test_accept_records_a_requirement_scoped_versioned_consent(self):
        application = self._apply("CITIZEN_C6C_001")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_001"))

        with Session(engine) as session:
            rows = session.execute(select(ConsentRow).where(ConsentRow.citizen_id == "CITIZEN_C6C_001")).scalars().all()
        self.assertEqual(len(rows), 1)
        receipt = rows[0].payload
        self.assertEqual(receipt["applicationId"], application["appId"])
        self.assertEqual(receipt["purpose"], f"AUTO_FILL:{code}")
        self.assertEqual(receipt["decision"], "ALLOW")

    def test_accept_for_a_different_requirement_creates_a_differently_scoped_consent(self):
        application = self._apply("CITIZEN_C6C_002")
        code_a, code_b = application["requirements"][0]["requirementCode"], application["requirements"][1]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            auto_fill_requirement(application["appId"], code_a, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_002"))
            auto_fill_requirement(application["appId"], code_b, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_002"))

        with Session(engine) as session:
            rows = session.execute(select(ConsentRow).where(ConsentRow.citizen_id == "CITIZEN_C6C_002")).scalars().all()
        purposes = {row.payload["purpose"] for row in rows}
        self.assertEqual(purposes, {f"AUTO_FILL:{code_a}", f"AUTO_FILL:{code_b}"})

    # ------------------------------------------------------------------
    # 3: reject path
    # ------------------------------------------------------------------
    def test_reject_never_calls_the_provider_and_creates_no_consent_or_document(self):
        application = self._apply("CITIZEN_C6C_003")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider") as discover, \
             patch.object(requirement_fulfillment, "request_registered_service") as retrieve:
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="REJECT"), user=_user("CITIZEN_C6C_003"))
        discover.assert_not_called()
        retrieve.assert_not_called()
        with Session(engine) as session:
            self.assertEqual(session.execute(select(ConsentRow).where(ConsentRow.citizen_id == "CITIZEN_C6C_003")).scalars().all(), [])
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertIn(requirement["status"], {"NOT_PROVIDED", "ACTION_REQUIRED"})
        self.assertNotIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertIsNone(get_document(f"DOC-{application['appId']}-{code}"))

    def test_reject_message_is_generic_and_manual_upload_stays_available(self):
        application = self._apply("CITIZEN_C6C_004")
        document_code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        result = auto_fill_requirement(application["appId"], document_code, AutoFillDecision(decision="REJECT"), user=_user("CITIZEN_C6C_004"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == document_code)
        # Manual Upload stays available: the requirement is still a
        # document-type requirement in a non-terminal state, never silently
        # switched to something the upload endpoint would refuse.
        self.assertIn(requirement["dataType"], {"DOCUMENT", "CERTIFICATE"})
        self.assertNotIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertIn("upload the document yourself", requirement["userAction"].lower())
        self.assertTrue(requirement["canUpload"])

    def test_reject_does_not_undo_an_already_completed_requirement(self):
        application = self._apply("CITIZEN_C6C_005")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_005"))
        result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="REJECT"), user=_user("CITIZEN_C6C_005"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)

    # ------------------------------------------------------------------
    # 4: per-requirement isolation
    # ------------------------------------------------------------------
    def test_auto_fill_touches_only_the_selected_requirement(self):
        application = self._apply("CITIZEN_C6C_006")
        target = application["requirements"][1]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            result = auto_fill_requirement(application["appId"], target, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_006"))
        for item in result["requirements"]:
            if item["requirementCode"] == target:
                continue
            self.assertEqual(item["status"], "NOT_PROVIDED")

    # ------------------------------------------------------------------
    # 5-6: dynamic provider discovery, never hardcoded / never frontend-chosen
    # ------------------------------------------------------------------
    def test_provider_is_discovered_dynamically_not_hardcoded(self):
        application = self._apply("CITIZEN_C6C_007")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-DYNAMIC-42"}) as discover, \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()) as retrieve:
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_007"))
        discover.assert_called_once()
        self.assertEqual(discover.call_args.args[0], code)
        retrieve.assert_called_once()
        self.assertEqual(retrieve.call_args.args[0], "SVC-DYNAMIC-42")

    def test_auto_fill_route_has_no_provider_or_department_literal(self):
        source = (BACKEND_ROOT / "app" / "api" / "citizen_routes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "auto_fill_requirement")
        body_source = ast.get_source_segment(source, function)
        for literal in ("Revenue Department", "Social Welfare Department", "Education Department", "DigiLocker", "API Setu"):
            self.assertNotIn(literal, body_source)
        fulfillment_source = (BACKEND_ROOT / "app" / "engine" / "requirement_fulfillment.py").read_text(encoding="utf-8")
        for literal in ("Revenue Department", "Social Welfare Department", "Education Department"):
            self.assertNotIn(literal, fulfillment_source)
        self.assertIn("select_dependency_provider", fulfillment_source)

    def test_auto_fill_request_body_cannot_supply_a_provider(self):
        self.assertEqual(set(AutoFillDecision.model_fields), {"decision"})

    # ------------------------------------------------------------------
    # 7-8: document vs non-document behaviour
    # ------------------------------------------------------------------
    def test_successful_auto_fill_on_a_document_requirement_creates_a_document(self):
        application = self._apply("CITIZEN_C6C_008")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_008"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "VALIDATED")
        document = get_document(f"DOC-{application['appId']}-{code}")
        self.assertIsNotNone(document)
        self.assertEqual(document["requirementCode"], code)
        self.assertEqual(document["citizenId"], "CITIZEN_C6C_008")

    def test_successful_auto_fill_on_a_non_document_requirement_creates_no_document(self):
        application = self._apply("CITIZEN_C6C_009")
        code = next((item["requirementCode"] for item in application["requirements"] if item.get("dataType") not in {"DOCUMENT", "CERTIFICATE"}), None)
        if code is None:
            self.skipTest("no non-document requirement on this scheme")
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_009"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "RETRIEVED")
        self.assertIsNone(get_document(f"DOC-{application['appId']}-{code}"))

    def test_repeated_success_does_not_create_a_second_document_row(self):
        application = self._apply("CITIZEN_C6C_010")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_010"))
            # Second Auto-Fill click on an already-VALIDATED requirement is a
            # no-op (idempotent): the provider must not be called again.
            with patch.object(requirement_fulfillment, "request_registered_service") as retrieve_again:
                auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_010"))
                retrieve_again.assert_not_called()
        with Session(engine) as session:
            rows = session.query(DocumentRow).filter(DocumentRow.document_id == f"DOC-{application['appId']}-{code}").all()
        self.assertEqual(len(rows), 1)

    # ------------------------------------------------------------------
    # 9: retry/failure taxonomy reuse (no second retry system)
    # ------------------------------------------------------------------
    def test_retryable_failure_below_attempt_limit_moves_to_waiting(self):
        application = self._apply("CITIZEN_C6C_011")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result("UPSTREAM_UNAVAILABLE", retryable=True)):
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_011"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "WAITING")
        internal = requirement_fulfillment.find_requirement(get_application_raw(application["appId"]), code)
        self.assertEqual(internal["attempts"], 1)

    def test_retryable_failure_exhausted_moves_to_action_required(self):
        application = self._apply("CITIZEN_C6C_012")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result("UPSTREAM_UNAVAILABLE", retryable=True)):
            for _ in range(3):
                result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_012"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "ACTION_REQUIRED")
        internal = requirement_fulfillment.find_requirement(get_application_raw(application["appId"]), code)
        self.assertEqual(internal["attempts"], 3)

    def test_non_retryable_failure_moves_to_failed(self):
        application = self._apply("CITIZEN_C6C_013")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result("VALIDATION_ERROR", retryable=False)):
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_013"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "FAILED")

    def test_failure_classification_reuses_retry_policy_taxonomy(self):
        """Confirms requirement_fulfillment does not define a second/parallel
        retryable-category taxonomy -- it defers to retry_policy, which in
        turn defers to the existing adapter error taxonomy."""
        requirement = {"attempts": 1, "maxAttempts": 3, "errorCategory": "TIMEOUT", "status": "WAITING"}
        classification = requirement_fulfillment.retry_policy.classify_dependency_failure(requirement)
        self.assertTrue(classification["retryable"])
        self.assertTrue(classification["knownCategory"])

    # ------------------------------------------------------------------
    # 10: validation failure never falsely completes a requirement
    # ------------------------------------------------------------------
    def test_adapter_success_with_failing_validation_is_rejected_not_completed(self):
        application = self._apply("CITIZEN_C6C_014")
        code = next(item["requirementCode"] for item in application["requirements"] if item["requirementCode"] == "INCOME_PROOF")
        negative_income = _success_result(canonical={"incomeAmount": -500})
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=negative_income):
            result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_014"))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "REJECTED")
        self.assertNotIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
        internal = requirement_fulfillment.find_requirement(get_application_raw(application["appId"]), code)
        self.assertFalse(internal["validation"]["valid"])

    # ------------------------------------------------------------------
    # 11: consent authorization failure fails closed
    # ------------------------------------------------------------------
    def test_invalid_consent_never_reaches_the_provider(self):
        application = self._apply("CITIZEN_C6C_015")
        code = application["requirements"][0]["requirementCode"]
        with patch("app.engine.requirement_fulfillment.execute_with_persisted_authorization", side_effect=ConsentAuthorizationError("denied")), \
             patch.object(requirement_fulfillment, "request_registered_service") as retrieve:
            with self.assertRaises(HTTPException) as ctx:
                auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_015"))
        self.assertEqual(ctx.exception.status_code, 403)
        retrieve.assert_not_called()

    # ------------------------------------------------------------------
    # 12: cross-citizen denial
    # ------------------------------------------------------------------
    def test_citizen_cannot_auto_fill_another_citizens_requirement(self):
        application = self._apply("CITIZEN_C6C_016")
        code = application["requirements"][0]["requirementCode"]
        with self.assertRaises(HTTPException) as ctx:
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_017"))
        self.assertEqual(ctx.exception.status_code, 404)

    # ------------------------------------------------------------------
    # 13-14: concurrent execution + failure isolation
    # ------------------------------------------------------------------
    def test_concurrent_auto_fill_on_different_requirements_are_independent(self):
        application = self._apply("CITIZEN_C6C_018")
        codes = [item["requirementCode"] for item in application["requirements"][:3]]

        def fake_retrieve(service_id, citizen_id, requirement_code=None, correlation_id=None, idempotency_key=None):
            if requirement_code == codes[0]:
                return _success_result(record_id="REC-A")
            if requirement_code == codes[1]:
                return _failure_result("UPSTREAM_UNAVAILABLE", retryable=True)
            return _failure_result("VALIDATION_ERROR", retryable=False)

        results = {}
        errors = []

        def run(code):
            try:
                results[code] = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_C6C_018"))
            except Exception as error:  # pragma: no cover - failure would show up in assertions below
                errors.append((code, error))

        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=fake_retrieve):
            threads = [threading.Thread(target=run, args=(code,)) for code in codes]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

        self.assertEqual(errors, [])
        final = get_citizen_application(application["appId"], user=_user("CITIZEN_C6C_018"))
        by_code = {item["requirementCode"]: item for item in final["requirements"]}
        self.assertIn(by_code[codes[0]]["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertEqual(by_code[codes[1]]["status"], "WAITING")
        self.assertEqual(by_code[codes[2]]["status"], "FAILED")
        # Requirements not touched by any thread remain untouched.
        for item in final["requirements"]:
            if item["requirementCode"] not in codes:
                self.assertEqual(item["status"], "NOT_PROVIDED")


class NoProviderLiteralInAutoFillTests(unittest.TestCase):
    def test_requirement_fulfillment_never_names_a_specific_provider_service_id(self):
        source = (BACKEND_ROOT / "app" / "engine" / "requirement_fulfillment.py").read_text(encoding="utf-8")
        for literal in ("REV-MAHA-101", "REV-INCOME-102", "SW-CASTE-301", "EDU-ACA-201", "DBT-BANK-401"):
            self.assertNotIn(literal, source)


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
