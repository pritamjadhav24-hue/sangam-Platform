"""Phase 6E: Review -> Submit for authoritative (Phase 6B+) citizen
applications.

Route handlers are called directly as plain functions, matching this
codebase's established test convention. Provider discovery/adapter calls are
mocked for the requirement-satisfying steps; submission itself always goes
through the real authoritative persistence path (app.engine.submission,
persistence.transition_application_status) -- nothing about submission is
mocked, since that is exactly what this phase must prove works.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.citizen_routes import (
    ApplySchemeRequest, AutoFillDecision, RequirementUpload, apply_to_scheme, auto_fill_requirement,
    get_citizen_application, submit_citizen_application, upload_requirement_document, track,
)
from app.core.persistence import (
    REQUIREMENT_CATALOG, ApplicationRow, ConsentRow, DocumentRow, RequirementCatalogRow,
    engine, get_application as get_application_raw, mutate_application, seed_requirement_catalog,
)
from app.engine import requirement_fulfillment, submission
from app.engine.adapters import AdapterResult

BACKEND_DEFAULT_MAX_ATTEMPTS = 3


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace())


def setUpModule():
    with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
        seed_requirement_catalog()


def tearDownModule():
    with Session(engine) as session:
        session.query(RequirementCatalogRow).filter(
            RequirementCatalogRow.requirement_code.in_([item["code"] for item in REQUIREMENT_CATALOG])
        ).delete(synchronize_session=False)
        session.commit()


def _success_result(record_id="REC-1"):
    # A canonical payload broad enough to pass every requirement-specific
    # rule in validation_engine.validate() (e.g. INCOME_PROOF's non-negative
    # income check, ACADEMIC_RECORD's 0-100 percentage check), since this
    # helper stands in for "any requirement's" successful Auto-Fill result.
    canonical = {"value": "ok", "incomeAmount": 100000, "percentage": 75}
    return AdapterResult({"id": record_id, "canonical": canonical, "validUntil": None}, success=True)


def _failure_result(category="UPSTREAM_UNAVAILABLE", retryable=True):
    return AdapterResult(None, success=False, error_category=category, retryable=retryable)


class ApplicationSubmissionTests(unittest.TestCase):
    def setUp(self):
        self._created_app_ids: list[str] = []
        self._created_citizen_ids: list[str] = []

    def tearDown(self):
        with Session(engine) as session:
            if self._created_app_ids:
                session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            if self._created_citizen_ids:
                session.query(ConsentRow).filter(ConsentRow.citizen_id.in_(self._created_citizen_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str = "SCH-MH-2026") -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._created_app_ids.append(application["appId"])
        self._created_citizen_ids.append(citizen_id)
        return application

    def _complete_all_requirements(self, application: dict, citizen_id: str) -> dict:
        result = application
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            for requirement in application["requirements"]:
                result = auto_fill_requirement(application["appId"], requirement["requirementCode"], AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        return result

    # ------------------------------------------------------------------
    # Readiness semantics
    # ------------------------------------------------------------------
    def test_complete_application_can_submit(self):
        application = self._apply("CITIZEN_6E_001")
        self._complete_all_requirements(application, "CITIZEN_6E_001")
        submitted = submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_001"))
        self.assertEqual(submitted["status"], "SUBMITTED")
        self.assertIn("submittedAt", submitted)

    def test_not_provided_requirement_blocks_submission(self):
        application = self._apply("CITIZEN_6E_002")
        # No requirements completed at all.
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_002"))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertGreater(len(ctx.exception.detail["blockingRequirements"]), 0)
        # Application remains editable/unsubmitted.
        current = get_application_raw(application["appId"])
        self.assertEqual(current["status"], "IN_PROGRESS")

    def test_waiting_requirement_blocks_submission(self):
        application = self._apply("CITIZEN_6E_003")
        self._complete_all_requirements(application, "CITIZEN_6E_003")
        # Knock one requirement back into a retryable-failure (WAITING) state.
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            with Session(engine) as session:
                from app.core.persistence import get_application
                locked = get_application(application["appId"], for_update=True, session=session)
                requirements = locked["requirements"]
                target = next(item for item in requirements if item["code"] == code)
                target["status"] = "NOT_PROVIDED"  # allow a fresh Auto-Fill attempt below
                mutate_application(application["appId"], {"requirements": requirements}, session=session)
                session.commit()
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6E_003"))
        current = get_application_raw(application["appId"])
        requirement = requirement_fulfillment.find_requirement(current, code)
        self.assertEqual(requirement["status"], "WAITING")
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_003"))
        self.assertEqual(ctx.exception.status_code, 422)
        blocking_codes = {item["requirementCode"] for item in ctx.exception.detail["blockingRequirements"]}
        self.assertIn(code, blocking_codes)

    def test_action_required_requirement_blocks_submission(self):
        application = self._apply("CITIZEN_6E_004")
        code = application["requirements"][0]["requirementCode"]
        auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="REJECT"), user=_user("CITIZEN_6E_004"))
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_004"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_failed_requirement_blocks_submission(self):
        application = self._apply("CITIZEN_6E_005")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result("VALIDATION_ERROR", retryable=False)):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6E_005"))
        current = get_application_raw(application["appId"])
        self.assertEqual(requirement_fulfillment.find_requirement(current, code)["status"], "FAILED")
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_005"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_optional_requirement_does_not_block_submission(self):
        application = self._apply("CITIZEN_6E_006")
        # Mark one requirement optional directly (the current catalogue's
        # schemes don't happen to define any optional requirement, so this
        # proves the *mechanism* works using the existing 'mandatory' field
        # rather than assuming a specific scheme's data).
        with Session(engine) as session:
            from app.core.persistence import get_application
            locked = get_application(application["appId"], for_update=True, session=session)
            requirements = locked["requirements"]
            requirements[0]["mandatory"] = False
            mutate_application(application["appId"], {"requirements": requirements}, session=session)
            session.commit()
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            for requirement in application["requirements"][1:]:
                auto_fill_requirement(application["appId"], requirement["requirementCode"], AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6E_006"))
        # requirements[0] (optional, still NOT_PROVIDED) must not block.
        submitted = submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_006"))
        self.assertEqual(submitted["status"], "SUBMITTED")

    def test_unknown_requirement_status_blocks_submission_fail_closed(self):
        """Security: a malformed/unrecognised status value must never be
        treated as satisfied -- readiness fails closed."""
        application = self._apply("CITIZEN_6E_007")
        with Session(engine) as session:
            from app.core.persistence import get_application
            locked = get_application(application["appId"], for_update=True, session=session)
            requirements = locked["requirements"]
            for requirement in requirements:
                requirement["status"] = "SOME_UNKNOWN_STATUS"
            mutate_application(application["appId"], {"requirements": requirements}, session=session)
            session.commit()
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_007"))
        self.assertEqual(ctx.exception.status_code, 422)

    # ------------------------------------------------------------------
    # Security / ownership
    # ------------------------------------------------------------------
    def test_citizen_cannot_submit_another_citizens_application(self):
        application = self._apply("CITIZEN_6E_008")
        self._complete_all_requirements(application, "CITIZEN_6E_008")
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_999"))
        self.assertEqual(ctx.exception.status_code, 404)
        current = get_application_raw(application["appId"])
        self.assertEqual(current["status"], "IN_PROGRESS")

    def test_submit_nonexistent_application(self):
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application("APP-DOES-NOT-EXIST-00000", user=_user("CITIZEN_6E_009"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_submission_response_has_no_provider_or_department_fields(self):
        application = self._apply("CITIZEN_6E_010")
        self._complete_all_requirements(application, "CITIZEN_6E_010")
        submitted = submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_010"))
        blob = str(submitted)
        for forbidden in ("providerId", "Revenue Department", "Social Welfare Department", "Education Department", "DigiLocker", "API Setu", "adapter", "sourceType"):
            self.assertNotIn(forbidden, blob)

    # ------------------------------------------------------------------
    # Persistence / idempotency / concurrency
    # ------------------------------------------------------------------
    def test_submitted_state_survives_a_simulated_refresh(self):
        application = self._apply("CITIZEN_6E_011")
        self._complete_all_requirements(application, "CITIZEN_6E_011")
        submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_011"))
        refreshed = get_citizen_application(application["appId"], user=_user("CITIZEN_6E_011"))
        self.assertEqual(refreshed["status"], "SUBMITTED")
        self.assertIn("submittedAt", refreshed)

    def test_repeated_submission_is_idempotent(self):
        application = self._apply("CITIZEN_6E_012")
        self._complete_all_requirements(application, "CITIZEN_6E_012")
        first = submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_012"))
        second = submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_012"))
        self.assertEqual(first["status"], "SUBMITTED")
        self.assertEqual(second["status"], "SUBMITTED")
        self.assertEqual(first["submittedAt"], second["submittedAt"])
        with Session(engine) as session:
            from app.core.persistence import WorkflowHistoryRow
            history = session.query(WorkflowHistoryRow).filter_by(app_id=application["appId"], status="SUBMITTED").all()
        self.assertEqual(len(history), 1, "a repeated submission must not create a second SUBMITTED history entry")

    def test_concurrent_double_submit_produces_exactly_one_submission(self):
        application = self._apply("CITIZEN_6E_013")
        self._complete_all_requirements(application, "CITIZEN_6E_013")

        results = []
        errors = []
        barrier = threading.Barrier(2, timeout=10)

        def run():
            try:
                barrier.wait()
                results.append(submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_013")))
            except Exception as error:  # pragma: no cover
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item["status"] == "SUBMITTED" for item in results))
        with Session(engine) as session:
            from app.core.persistence import WorkflowHistoryRow
            history = session.query(WorkflowHistoryRow).filter_by(app_id=application["appId"], status="SUBMITTED").all()
        self.assertEqual(len(history), 1, "concurrent double-submit must produce exactly one submission event")

    def test_submit_while_a_requirement_is_still_unresolved_is_rejected_not_partially_succeeded(self):
        """Race A: a citizen attempts Submit while a requirement has not
        finished (is still WAITING) -- submission must not incorrectly
        succeed, and the application must remain editable afterward."""
        application = self._apply("CITIZEN_6E_014")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6E_014"))
        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_014"))
        self.assertEqual(ctx.exception.status_code, 422)
        current = get_application_raw(application["appId"])
        self.assertEqual(current["status"], "IN_PROGRESS")

    # ------------------------------------------------------------------
    # Submitted-application immutability
    # ------------------------------------------------------------------
    def test_submitted_application_rejects_further_auto_fill(self):
        application = self._apply("CITIZEN_6E_015")
        self._complete_all_requirements(application, "CITIZEN_6E_015")
        submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_015"))

        # Force one requirement back to a mutable-looking state directly in
        # storage to prove the *submitted guard* is what blocks the next
        # Auto-Fill call, not an accidental idempotency short-circuit.
        with Session(engine) as session:
            from app.core.persistence import get_application
            locked = get_application(application["appId"], for_update=True, session=session)
            requirements = locked["requirements"]
            requirements[0]["status"] = "NOT_PROVIDED"
            mutate_application(application["appId"], {"requirements": requirements}, session=session)
            session.commit()

        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            with self.assertRaises(HTTPException) as ctx:
                auto_fill_requirement(application["appId"], application["requirements"][0]["requirementCode"], AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6E_015"))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_submitted_application_rejects_further_manual_upload(self):
        application = self._apply("CITIZEN_6E_016")
        self._complete_all_requirements(application, "CITIZEN_6E_016")
        submit_citizen_application(application["appId"], user=_user("CITIZEN_6E_016"))

        document_code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        with self.assertRaises(HTTPException) as ctx:
            upload_requirement_document(application["appId"], document_code, RequirementUpload(title="x", content="y"), user=_user("CITIZEN_6E_016"))
        self.assertEqual(ctx.exception.status_code, 409)
    def test_authoritative_application_can_be_tracked_by_owner(self):
        application = self._apply("CITIZEN_6E_017")
        tracked = track(application["appId"], user=_user("CITIZEN_6E_017"))
        self.assertEqual(tracked["appId"], application["appId"])
        self.assertEqual(tracked["status"], "IN_PROGRESS")
        self.assertIn("requirements", tracked)

    def test_authoritative_application_tracking_blocks_other_citizens(self):
        application = self._apply("CITIZEN_6E_018")
        with self.assertRaises(HTTPException) as ctx:
            track(application["appId"], user=_user("OTHER_CITIZEN"))
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
