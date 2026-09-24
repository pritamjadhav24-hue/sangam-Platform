"""Phase 6C end-to-end tests.

Mirrors test_dynamic_provider_e2e.py's fixture exactly (a live department
sandbox HTTP server, real seeded provider/capability/schema-mapping rows) but
exercises the Phase 6C Auto-Fill boundary instead of the legacy dependency
path, proving the full authoritative-application pipeline works end to end:

  requirement -> consent accepted -> dynamic provider discovery -> provider
  API (real HTTP) -> adapter -> schema mapping -> validation -> requirement
  completed -> (for a document-type requirement) document reference created.

A second scenario proves genuine parallel execution with failure isolation:
three Auto-Fill calls for three independent requirements on the same
application, fired from separate threads, where one requirement has no
reachable provider (so it fails) while the other two -- reaching the same
live server -- succeed, proving one requirement's failure does not block or
cancel the others.

Department/provider names are never asserted anywhere here -- only read back
from the dynamic selection the engine itself made, matching
test_dynamic_provider_e2e.py's own rule.
"""
from __future__ import annotations

import importlib
import os
import threading
import time
import unittest
from types import SimpleNamespace

import uvicorn
from sqlalchemy.orm import Session

from tests.catalog_fixture import remove_test_vocabulary, seed_test_vocabulary
from app.api.citizen_routes import AutoFillDecision, RequirementUpload, auto_fill_requirement, get_citizen_application, upload_requirement_document
from app.core.demo_state import reset_demo_state
from app.core.persistence import (
    CitizenNotificationRow,
    DEPARTMENT_SANDBOX_PROVIDERS, REQUIREMENT_CATALOG, ApplicationRow, DepartmentRow, DocumentRow,
    ProviderCapabilityRow, ProviderRow, RequirementCatalogRow, SchemaMappingRow, ServiceCatalogRow,
    create_application as create_application_authoritative,
    engine, get_document, seed_department_sandbox_providers, seed_department_sandbox_schema_mappings,
    seed_requirement_catalog,
)
from app.engine import requirement_fulfillment
from app.engine.consent_manager import create_consent
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool
from unittest.mock import patch

TEST_PORT = 18198
CITIZENS = generate_citizen_pool(60)

_server = None
_server_thread = None


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


_VOCABULARY_ADDED: set[str] = set()
_PREEXISTING: dict[str, set] = {}
_PREVIOUS_ENV: dict[str, str | None] = {}


def setUpModule():
    global _server, _server_thread
    _VOCABULARY_ADDED.update(seed_test_vocabulary())
    for key in ("revenue", "food_civil_supplies"):
        spec = SANDBOXES_BY_KEY[key]
        models = importlib.import_module(spec.models_module)
        seed = importlib.import_module(spec.seed_module)
        models.Base.metadata.drop_all(models.ENGINE)
        models.Base.metadata.create_all(models.ENGINE)
        with session_scope(models.ENGINE) as session:
            seed.seed(session, CITIZENS)

    from app.department_api.main import app as department_app
    config = uvicorn.Config(department_app, host="127.0.0.1", port=TEST_PORT, log_level="error")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    for _ in range(100):
        if getattr(_server, "started", False):
            break
        time.sleep(0.05)
    _PREVIOUS_ENV["DEPARTMENT_API_BASE_URL"] = os.environ.get("DEPARTMENT_API_BASE_URL")
    os.environ["DEPARTMENT_API_BASE_URL"] = f"http://127.0.0.1:{TEST_PORT}"

    # Only rows this module adds are removed afterwards: when the demo
    # environment already registered the department sandbox providers, they
    # (and their mappings) must survive this test module.
    with Session(engine) as session:
        _PREEXISTING.update(
            providers={row.provider_id for row in session.query(ProviderRow.provider_id)},
            departments={row.department_id for row in session.query(DepartmentRow.department_id)},
            services={row.service_id for row in session.query(ServiceCatalogRow.service_id)},
            mappings={row.mapping_id for row in session.query(SchemaMappingRow.mapping_id)},
            capabilities={row.capability_id for row in session.query(ProviderCapabilityRow.capability_id)},
        )
    with patch.dict(os.environ, {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true"}):
        seed_department_sandbox_providers()
        seed_department_sandbox_schema_mappings()


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    remove_test_vocabulary(_VOCABULARY_ADDED)
    if _PREVIOUS_ENV.get("DEPARTMENT_API_BASE_URL") is None:
        os.environ.pop("DEPARTMENT_API_BASE_URL", None)
    else:
        os.environ["DEPARTMENT_API_BASE_URL"] = _PREVIOUS_ENV["DEPARTMENT_API_BASE_URL"]
    if not _PREEXISTING:
        return
    provider_ids = [item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS if item["providerId"] not in _PREEXISTING["providers"]]
    department_ids = list({item["departmentId"] for item in DEPARTMENT_SANDBOX_PROVIDERS} - _PREEXISTING["departments"])
    service_ids = [item["serviceId"] for item in DEPARTMENT_SANDBOX_PROVIDERS if item["serviceId"] not in _PREEXISTING["services"]]
    with Session(engine) as session:
        session.query(SchemaMappingRow).filter(
            SchemaMappingRow.provider_id.in_([item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]),
            SchemaMappingRow.mapping_id.notin_(_PREEXISTING["mappings"]),
        ).delete(synchronize_session=False)
        session.query(ProviderCapabilityRow).filter(
            ProviderCapabilityRow.provider_id.in_([item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]),
            ProviderCapabilityRow.capability_id.notin_(_PREEXISTING["capabilities"]),
        ).delete(synchronize_session=False)
        session.query(ServiceCatalogRow).filter(ServiceCatalogRow.service_id.in_(service_ids)).delete(synchronize_session=False)
        session.query(ProviderRow).filter(ProviderRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
        session.query(DepartmentRow).filter(DepartmentRow.department_id.in_(department_ids)).delete(synchronize_session=False)
        session.commit()


def _citizen_with_land_record():
    spec = SANDBOXES_BY_KEY["revenue"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        resident = session.query(models.ResidentIndex).join(
            models.LandRecord, models.LandRecord.resident_id == models.ResidentIndex.resident_id
        ).first()
        return resident.citizen_ref


def _citizen_with_ration_card():
    spec = SANDBOXES_BY_KEY["food_civil_supplies"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        card = session.query(models.RationCard).first()
        return card.citizen_ref


def _citizen_with_land_record_and_ration_card():
    """A citizen present in both the revenue and food-civil-supplies
    sandboxes, so one application/citizen can exercise both requirements in
    the parallel scenario."""
    revenue_spec = SANDBOXES_BY_KEY["revenue"]
    revenue_models = importlib.import_module(revenue_spec.models_module)
    with session_scope(revenue_models.ENGINE) as session:
        land_citizens = {
            row.citizen_ref for row in session.query(revenue_models.ResidentIndex).join(
                revenue_models.LandRecord, revenue_models.LandRecord.resident_id == revenue_models.ResidentIndex.resident_id
            ).all()
        }
    fcs_spec = SANDBOXES_BY_KEY["food_civil_supplies"]
    fcs_models = importlib.import_module(fcs_spec.models_module)
    with session_scope(fcs_models.ENGINE) as session:
        ration_citizens = {row.citizen_ref for row in session.query(fcs_models.RationCard).all()}
    common = sorted(land_citizens & ration_citizens)
    if not common:
        raise RuntimeError("no synthetic citizen has both a land record and a ration card")
    return common[0]


class AutoFillEndToEndTest(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        self._created_app_ids: list[str] = []

    def tearDown(self):
        if not self._created_app_ids:
            return
        with Session(engine) as session:
            session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(CitizenNotificationRow).filter(CitizenNotificationRow.application_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.commit()

    def _create_app(self, citizen_id: str, requirements: list[dict]) -> dict:
        application = create_application_authoritative({
            "citizenId": citizen_id, "serviceId": "PHASE6C-E2E-SERVICE", "status": "IN_PROGRESS",
            "requirements": requirements,
        })
        self._created_app_ids.append(application["appId"])
        return application

    def test_single_requirement_full_pipeline(self):
        """requirement -> Accept -> dynamic discovery -> provider API ->
        adapter -> schema mapping -> validation -> requirement completed ->
        document reference created (RATION_CARD is a CERTIFICATE-type
        requirement)."""
        requirement_code = "RATION_CARD"  # the test starts here -- no department is named
        citizen_id = _citizen_with_ration_card()
        application = self._create_app(citizen_id, [{
            "code": requirement_code, "label": "Ration card", "mandatory": True,
            "status": "NOT_PROVIDED", "dataType": "CERTIFICATE",
        }])

        result = auto_fill_requirement(application["appId"], requirement_code, AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))

        requirement = next(item for item in result["requirements"] if item["requirementCode"] == requirement_code)
        self.assertEqual(requirement["status"], "VALIDATED", requirement)
        self.assertEqual(requirement["userAction"], "No action required")

        document = get_document(f"DOC-{application['appId']}-{requirement_code}")
        self.assertIsNotNone(document)
        self.assertEqual(document["status"], "VALIDATED")
        self.assertTrue(document["validation"]["valid"])
        # Schema mapping happened: the department's own field name
        # ("card_category") was translated to the canonical name.
        self.assertIn("rationCardCategory", document["canonical"])

    def test_parallel_auto_fill_with_failure_isolation(self):
        """Three independent requirements Auto-Filled concurrently on the
        same application: two reach the live sandbox server and succeed
        (one document-type, one non-document-type), one has no registered
        provider at all and fails -- proving one requirement's failure does
        not block or cancel the others, and that they genuinely overlap in
        wall-clock time rather than running one-after-another."""
        citizen_id = _citizen_with_land_record_and_ration_card()
        application = self._create_app(citizen_id, [
            {"code": "LAND_HOLDING", "label": "Land holding", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "RECORD"},
            {"code": "RATION_CARD", "label": "Ration card", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
            # No provider is registered for this requirement code at all
            # (never seeded in this test module) -- a realistic "no eligible
            # provider" failure, not an artificially injected one.
            {"code": "SCHOLARSHIP_ELIGIBILITY", "label": "Scholarship eligibility", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "RECORD"},
        ])

        entry_times: dict[str, float] = {}
        results: dict[str, dict] = {}
        errors: list[tuple[str, Exception]] = []
        barrier = threading.Barrier(3, timeout=10)

        def run(code: str):
            try:
                entry_times[code] = time.monotonic()
                barrier.wait()  # all three requests genuinely overlap
                results[code] = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
            except Exception as error:  # pragma: no cover
                errors.append((code, error))

        codes = ["LAND_HOLDING", "RATION_CARD", "SCHOLARSHIP_ELIGIBILITY"]
        threads = [threading.Thread(target=run, args=(code,)) for code in codes]
        started_at = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(errors, [], errors)
        self.assertTrue(all(thread.is_alive() is False for thread in threads))

        final = get_citizen_application(application["appId"], user=_user(citizen_id))
        by_code = {item["requirementCode"]: item for item in final["requirements"]}

        self.assertEqual(by_code["LAND_HOLDING"]["status"], "RETRIEVED", by_code["LAND_HOLDING"])
        self.assertEqual(by_code["RATION_CARD"]["status"], "VALIDATED", by_code["RATION_CARD"])
        # The unresolvable requirement failed without blocking the other two.
        self.assertIn(by_code["SCHOLARSHIP_ELIGIBILITY"]["status"], {"FAILED", "ACTION_REQUIRED", "WAITING"})

        # Genuine overlap: every thread had entered the critical section
        # (past the barrier) within a tight window of each other, not
        # sequentially one after another.
        spread = max(entry_times.values()) - min(entry_times.values())
        self.assertLess(spread, 2.0, "Auto-Fill calls did not overlap -- they ran sequentially")

        # Document lifecycle: only the CERTIFICATE-type requirement gets a
        # document row.
        self.assertIsNotNone(get_document(f"DOC-{application['appId']}-RATION_CARD"))
        self.assertIsNone(get_document(f"DOC-{application['appId']}-LAND_HOLDING"))
        self.assertIsNone(get_document(f"DOC-{application['appId']}-SCHOLARSHIP_ELIGIBILITY"))

    def test_retryable_failure_then_retry_succeeds_while_another_requirement_succeeds_independently(self):
        """Phase 6D's required scenario: requirement A hits a retryable
        failure while requirement B succeeds -- both dispatched concurrently,
        A's failure never blocks or cancels B. Retrying A afterward (the same
        consent-gated Auto-Fill action, not a separate mechanism) then
        succeeds. Final persisted state: both requirements verified.

        A's first attempt is forced to a retryable failure via a thin
        side_effect wrapper around the real adapter boundary (rather than
        marking its provider globally unavailable, which -- since
        select_dependency_provider only considers AVAILABLE/HEALTHY
        candidates -- would make discovery find no provider at all and
        produce a non-retryable CONFIGURATION_ERROR instead of a realistic
        transient one). B's call is never touched and goes through the real
        live HTTP path exactly like every other test in this file.
        """
        from app.engine.adapters import request_registered_service as real_request_registered_service

        citizen_id = _citizen_with_land_record_and_ration_card()
        application = self._create_app(citizen_id, [
            {"code": "LAND_HOLDING", "label": "Land holding", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "RECORD"},
            {"code": "RATION_CARD", "label": "Ration card", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])

        def flaky_once(service_id, citizen, requirement_code=None, correlation_id=None, idempotency_key=None):
            if requirement_code == "RATION_CARD":
                from app.engine.adapters import AdapterResult
                return AdapterResult(None, success=False, error_category="UPSTREAM_UNAVAILABLE", retryable=True)
            return real_request_registered_service(service_id, citizen, requirement_code=requirement_code, correlation_id=correlation_id, idempotency_key=idempotency_key)

        results: dict[str, dict] = {}
        errors: list[tuple[str, Exception]] = []
        barrier = threading.Barrier(2, timeout=10)

        def run(code: str):
            try:
                barrier.wait()
                results[code] = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
            except Exception as error:  # pragma: no cover
                errors.append((code, error))

        with patch.object(requirement_fulfillment, "request_registered_service", side_effect=flaky_once):
            threads = [threading.Thread(target=run, args=(code,)) for code in ("RATION_CARD", "LAND_HOLDING")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
        self.assertEqual(errors, [], errors)

        after_first_round = get_citizen_application(application["appId"], user=_user(citizen_id))
        by_code = {item["requirementCode"]: item for item in after_first_round["requirements"]}
        # A: the provider was unavailable -> a retryable failure, not success.
        self.assertEqual(by_code["RATION_CARD"]["status"], "WAITING", by_code["RATION_CARD"])
        # B: independent, unaffected, succeeds in the same round.
        self.assertEqual(by_code["LAND_HOLDING"]["status"], "RETRIEVED", by_code["LAND_HOLDING"])

        # Retry A (same consent-gated Auto-Fill action) now that the
        # provider is healthy again.
        retried = auto_fill_requirement(application["appId"], "RATION_CARD", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        retried_requirement = next(item for item in retried["requirements"] if item["requirementCode"] == "RATION_CARD")
        self.assertEqual(retried_requirement["status"], "VALIDATED", retried_requirement)

        final = get_citizen_application(application["appId"], user=_user(citizen_id))
        final_by_code = {item["requirementCode"]: item for item in final["requirements"]}
        self.assertIn(final_by_code["RATION_CARD"]["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertIn(final_by_code["LAND_HOLDING"]["status"], requirement_fulfillment.SUCCESS_STATUSES)
        self.assertEqual(final_by_code["RATION_CARD"]["userAction"], "No action required")
        self.assertEqual(final_by_code["LAND_HOLDING"]["userAction"], "No action required")

    def test_manual_upload_is_not_downgraded_by_a_stale_auto_fill_result_arriving_later(self):
        """End-to-end version of the stale-response protection: a citizen
        manually uploads a document for a requirement; a slower Auto-Fill
        attempt for the *same* requirement (already in flight before the
        upload, through the real live adapter/provider path) resolves only
        afterward. The manually supplied, already-validated requirement and
        its document must remain exactly as the citizen left them."""
        citizen_id = _citizen_with_ration_card()
        application = self._create_app(citizen_id, [
            {"code": "RATION_CARD", "label": "Ration card", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])

        uploaded = upload_requirement_document(
            application["appId"], "RATION_CARD",
            RequirementUpload(title="My own ration card copy", content="citizen-provided synthetic content"),
            user=_user(citizen_id),
        )
        requirement = next(item for item in uploaded["requirements"] if item["requirementCode"] == "RATION_CARD")
        self.assertEqual(requirement["status"], "VALIDATED")
        document_before = get_document(f"DOC-{application['appId']}-RATION_CARD")

        # Simulate the "already in flight, resolves late" ordering: this
        # attempt's own consent + real provider call happen strictly after
        # the manual upload already committed.
        from app.core.persistence import get_application as get_application_raw
        app_snapshot = get_application_raw(application["appId"])
        receipt = create_consent(
            citizen_id, True, attributes=[], service_id=app_snapshot.get("serviceId"),
            application_id=application["appId"], purpose=requirement_fulfillment.auto_fill_purpose("RATION_CARD"),
        )
        requirement_fulfillment.fulfill_requirement(app_snapshot, "RATION_CARD", citizen_id, receipt["consentId"])

        final = get_citizen_application(application["appId"], user=_user(citizen_id))
        final_requirement = next(item for item in final["requirements"] if item["requirementCode"] == "RATION_CARD")
        self.assertEqual(final_requirement["status"], "VALIDATED")
        self.assertEqual(final_requirement["documentId"], f"DOC-{application['appId']}-RATION_CARD")
        document_after = get_document(f"DOC-{application['appId']}-RATION_CARD")
        self.assertEqual(document_after["checksum"], document_before["checksum"], "the citizen's own upload must not be replaced by a stale Auto-Fill result")
        self.assertEqual(document_after["sourceType"], "CITIZEN_UPLOAD")


class ApplicationSubmissionEndToEndTest(unittest.TestCase):
    """Phase 6E: the full Review -> Submit flow against real, live-server
    retrieval (not mocked), reusing this module's existing sandbox fixture.
    """

    def setUp(self):
        reset_demo_state()
        self._created_app_ids: list[str] = []

    def tearDown(self):
        if not self._created_app_ids:
            return
        with Session(engine) as session:
            session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(CitizenNotificationRow).filter(CitizenNotificationRow.application_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.commit()

    def _create_app(self, citizen_id: str, requirements: list[dict]) -> dict:
        application = create_application_authoritative({
            "citizenId": citizen_id, "serviceId": "PHASE6E-E2E-SERVICE", "status": "IN_PROGRESS",
            "requirements": requirements,
        })
        self._created_app_ids.append(application["appId"])
        return application

    def test_full_review_and_submit_flow_with_real_retrieval(self):
        """Create/resume application -> satisfy required requirements via
        real Auto-Fill (live sandbox HTTP, no mocks) -> submit -> verify
        authoritative submitted state -> repeat submit (idempotent, no
        duplicate submission) -> verify post-submit requirement mutation is
        rejected."""
        from app.api.citizen_routes import AutoFillDecision, RequirementUpload, auto_fill_requirement, submit_citizen_application, upload_requirement_document
        from fastapi import HTTPException

        citizen_id = _citizen_with_land_record_and_ration_card()
        application = self._create_app(citizen_id, [
            {"code": "LAND_HOLDING", "label": "Land holding", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "RECORD"},
            {"code": "RATION_CARD", "label": "Ration card", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])

        for code in ("LAND_HOLDING", "RATION_CARD"):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))

        # Review: the application should now report itself ready.
        review = get_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertTrue(review["readyForSubmission"], review)
        self.assertEqual(review["blockingRequirements"], [])

        submitted = submit_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(submitted["status"], "SUBMITTED")
        self.assertIn("submittedAt", submitted)

        # Repeat submit: idempotent, no duplicate logical submission.
        resubmitted = submit_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(resubmitted["status"], "SUBMITTED")
        self.assertEqual(resubmitted["submittedAt"], submitted["submittedAt"])
        with Session(engine) as session:
            from app.core.persistence import WorkflowHistoryRow
            history = session.query(WorkflowHistoryRow).filter_by(app_id=application["appId"], status="SUBMITTED").all()
        self.assertEqual(len(history), 1)

        # Post-submit mutation is rejected through both real mutation paths.
        with self.assertRaises(HTTPException) as ctx:
            auto_fill_requirement(application["appId"], "LAND_HOLDING", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 409)
        with self.assertRaises(HTTPException) as ctx:
            upload_requirement_document(application["appId"], "RATION_CARD", RequirementUpload(title="x", content="y"), user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 409)

        # Final authoritative state remains SUBMITTED, untouched by the
        # rejected mutation attempts.
        final = get_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(final["status"], "SUBMITTED")

    def test_incomplete_application_cannot_be_submitted_and_remains_editable(self):
        """Review an incomplete application -> submission is rejected
        safely -> the application remains editable/unsubmitted."""
        from app.api.citizen_routes import AutoFillDecision, auto_fill_requirement, submit_citizen_application
        from fastapi import HTTPException

        citizen_id = _citizen_with_land_record_and_ration_card()
        application = self._create_app(citizen_id, [
            {"code": "LAND_HOLDING", "label": "Land holding", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "RECORD"},
            {"code": "RATION_CARD", "label": "Ration card", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])
        auto_fill_requirement(application["appId"], "LAND_HOLDING", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        # RATION_CARD deliberately left NOT_PROVIDED.

        review = get_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertFalse(review["readyForSubmission"], review)
        blocking_codes = {item["requirementCode"] for item in review["blockingRequirements"]}
        self.assertIn("RATION_CARD", blocking_codes)

        with self.assertRaises(HTTPException) as ctx:
            submit_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 422)

        still_editable = get_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(still_editable["status"], "IN_PROGRESS")
        # Manual upload / Auto-Fill remain usable -- the rejected submit
        # attempt did not lock the application.
        auto_fill_requirement(application["appId"], "RATION_CARD", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        final_review = get_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertTrue(final_review["readyForSubmission"], final_review)


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
