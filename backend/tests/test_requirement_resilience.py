"""Phase 6D: resilience/recovery/stale-response protection for the
per-requirement Auto-Fill + manual-upload flow built in Phase 6C.

Route handlers are called directly as plain functions, matching this
codebase's established test convention (see test_dynamic_application_form.py
and test_auto_fill_consent_retrieval.py). Real provider discovery/adapter
calls are mocked here for speed/determinism; the required E2E concurrency +
stale-response scenarios (a live department sandbox server, genuine threads)
are covered separately in test_auto_fill_e2e.py.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.citizen_routes import (
    ApplySchemeRequest, AutoFillDecision, RequirementUpload, apply_to_scheme,
    auto_fill_requirement, get_citizen_application, upload_requirement_document,
)
from app.core.audit_bus import AuditBus
from app.core.persistence import (
    REQUIREMENT_CATALOG, ApplicationRow, ConsentRow, DocumentRow, RequirementCatalogRow,
    engine, get_application as get_application_raw, get_document, seed_requirement_catalog,
)
from app.engine import requirement_fulfillment
from app.engine.adapters import AdapterResult
from app.engine.consent_manager import create_consent

BACKEND_ROOT_USER = "CITIZEN"


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


def _success_result(record_id="REC-1", canonical=None):
    return AdapterResult({"id": record_id, "canonical": canonical or {"value": "ok"}, "validUntil": None}, success=True)


def _failure_result(category="UPSTREAM_UNAVAILABLE", retryable=True):
    return AdapterResult(None, success=False, error_category=category, retryable=retryable)


class RequirementResilienceTests(unittest.TestCase):
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

    # ------------------------------------------------------------------
    # Stale-response protection (task item 7)
    # ------------------------------------------------------------------
    def test_stale_failed_auto_fill_never_downgrades_a_manually_uploaded_requirement(self):
        application = self._apply("CITIZEN_6D_001")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})

        uploaded = upload_requirement_document(application["appId"], code, RequirementUpload(title="My cert", content="synthetic content"), user=_user("CITIZEN_6D_001"))
        requirement = next(item for item in uploaded["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "VALIDATED")
        document_before = get_document(f"DOC-{application['appId']}-{code}")

        # Simulate a slower Auto-Fill attempt that was already in flight
        # before the upload and only resolves (with a failure) afterward --
        # requirement_fulfillment.fulfill_requirement does its own fresh
        # locked read, so this exercises the exact same guard a real race
        # would hit.
        app_snapshot = get_application_raw(application["appId"])
        receipt = create_consent(
            "CITIZEN_6D_001", True, attributes=[], service_id=app_snapshot.get("serviceId"),
            application_id=application["appId"], purpose=requirement_fulfillment.auto_fill_purpose(code),
        )
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            requirement_fulfillment.fulfill_requirement(app_snapshot, code, "CITIZEN_6D_001", receipt["consentId"])

        final = get_application_raw(application["appId"])
        final_requirement = requirement_fulfillment.find_requirement(final, code)
        self.assertEqual(final_requirement["status"], "VALIDATED", "a stale Auto-Fill failure must not downgrade a manual upload")
        self.assertEqual(final_requirement["documentId"], f"DOC-{application['appId']}-{code}")
        document_after = get_document(f"DOC-{application['appId']}-{code}")
        self.assertEqual(document_after["status"], "VALIDATED")
        self.assertEqual(document_before["checksum"], document_after["checksum"], "the citizen's uploaded document must not be replaced")

    def test_stale_successful_auto_fill_does_not_overwrite_a_manual_upload_either(self):
        """Even a stale *successful* Auto-Fill outcome must not silently
        replace what the citizen explicitly uploaded -- once a requirement
        is satisfied, only a new explicit citizen action (another upload, or
        a fresh Auto-Fill the citizen deliberately re-triggers, which the
        route's own idempotency check never allows for an already-VALIDATED
        requirement) should change it again."""
        application = self._apply("CITIZEN_6D_002")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        upload_requirement_document(application["appId"], code, RequirementUpload(title="My cert", content="synthetic content"), user=_user("CITIZEN_6D_002"))
        document_before = get_document(f"DOC-{application['appId']}-{code}")

        app_snapshot = get_application_raw(application["appId"])
        receipt = create_consent(
            "CITIZEN_6D_002", True, attributes=[], service_id=app_snapshot.get("serviceId"),
            application_id=application["appId"], purpose=requirement_fulfillment.auto_fill_purpose(code),
        )
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result(record_id="REC-STALE")):
            requirement_fulfillment.fulfill_requirement(app_snapshot, code, "CITIZEN_6D_002", receipt["consentId"])

        final = get_application_raw(application["appId"])
        final_requirement = requirement_fulfillment.find_requirement(final, code)
        self.assertEqual(final_requirement["status"], "VALIDATED")
        self.assertNotEqual(final_requirement.get("resultReference"), "REC-STALE")
        document_after = get_document(f"DOC-{application['appId']}-{code}")
        self.assertEqual(document_before["checksum"], document_after["checksum"])

    def test_concurrent_manual_upload_and_auto_fill_on_different_requirements_lose_no_updates(self):
        """Regression test for the pre-6D lost-update race: manual upload
        used to read/patch the requirements list without the same row lock
        Auto-Fill uses, so a concurrent Auto-Fill for a *different*
        requirement could silently discard the upload (or vice versa)."""
        application = self._apply("CITIZEN_6D_003")
        document_codes = [item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"}]
        self.assertGreaterEqual(len(document_codes), 2, "scheme needs at least two document-type requirements for this test")
        upload_code, auto_fill_code = document_codes[0], document_codes[1]

        errors = []

        def do_upload():
            try:
                upload_requirement_document(application["appId"], upload_code, RequirementUpload(title="X", content="Y"), user=_user("CITIZEN_6D_003"))
            except Exception as error:  # pragma: no cover
                errors.append(("upload", error))

        def do_auto_fill():
            try:
                with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
                     patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
                    auto_fill_requirement(application["appId"], auto_fill_code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_003"))
            except Exception as error:  # pragma: no cover
                errors.append(("auto-fill", error))

        threads = [threading.Thread(target=do_upload), threading.Thread(target=do_auto_fill)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        final = get_citizen_application(application["appId"], user=_user("CITIZEN_6D_003"))
        by_code = {item["requirementCode"]: item for item in final["requirements"]}
        self.assertEqual(by_code[upload_code]["status"], "VALIDATED", "the manual upload must not have been lost")
        self.assertIn(by_code[auto_fill_code]["status"], requirement_fulfillment.SUCCESS_STATUSES, "the Auto-Fill result must not have been lost")

    # ------------------------------------------------------------------
    # Retry: success, exhaustion, and further retry after exhaustion
    # ------------------------------------------------------------------
    def test_retry_after_a_waiting_failure_succeeds(self):
        application = self._apply("CITIZEN_6D_004")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            first = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_004"))
        self.assertEqual(next(item for item in first["requirements"] if item["requirementCode"] == code)["status"], "WAITING")

        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            retried = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_004"))
        requirement = next(item for item in retried["requirements"] if item["requirementCode"] == code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)

    def test_retry_after_exhaustion_can_still_succeed(self):
        application = self._apply("CITIZEN_6D_005")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            for _ in range(3):
                result = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_005"))
        self.assertEqual(next(item for item in result["requirements"] if item["requirementCode"] == code)["status"], "ACTION_REQUIRED")

        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            recovered = auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_005"))
        requirement = next(item for item in recovered["requirements"] if item["requirementCode"] == code)
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)

    def test_repeated_failed_retries_never_create_a_document_row(self):
        application = self._apply("CITIZEN_6D_006")
        code = next(item["requirementCode"] for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            for _ in range(3):
                auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_006"))
        self.assertIsNone(get_document(f"DOC-{application['appId']}-{code}"))

    def test_each_retry_creates_its_own_fresh_consent_receipt(self):
        """Consent is never bypassed or reused across attempts -- every
        Accept (first attempt or retry) creates a new receipt."""
        application = self._apply("CITIZEN_6D_007")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_007"))
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_007"))
        with Session(engine) as session:
            rows = session.execute(select(ConsentRow).where(ConsentRow.citizen_id == "CITIZEN_6D_007")).scalars().all()
        self.assertEqual(len(rows), 2, "each Accept click must be its own consent event, not reused")
        consent_ids = {row.consent_id for row in rows}
        self.assertEqual(len(consent_ids), 2)

    # ------------------------------------------------------------------
    # Page refresh / resume persistence (task item 4)
    # ------------------------------------------------------------------
    def test_requirement_state_survives_a_simulated_page_refresh(self):
        """A 'refresh' is nothing more than a brand-new, independent read of
        the application -- there is no server-side session/request state to
        lose, since every route already reads straight from PostgreSQL."""
        application = self._apply("CITIZEN_6D_008")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_success_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_008"))

        # Two independent "refresh" reads -- both must agree and both must
        # be backend-driven, not reliant on anything cached client-side.
        first_refresh = get_citizen_application(application["appId"], user=_user("CITIZEN_6D_008"))
        second_refresh = get_citizen_application(application["appId"], user=_user("CITIZEN_6D_008"))
        for refreshed in (first_refresh, second_refresh):
            requirement = next(item for item in refreshed["requirements"] if item["requirementCode"] == code)
            self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES)
            self.assertEqual(requirement["userAction"], "No action required")

    def test_rejected_requirement_guidance_survives_refresh_without_local_state(self):
        application = self._apply("CITIZEN_6D_009")
        code = application["requirements"][0]["requirementCode"]
        auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="REJECT"), user=_user("CITIZEN_6D_009"))

        refreshed = get_citizen_application(application["appId"], user=_user("CITIZEN_6D_009"))
        requirement = next(item for item in refreshed["requirements"] if item["requirementCode"] == code)
        self.assertEqual(requirement["status"], "ACTION_REQUIRED")
        self.assertEqual(requirement["userAction"], "Automatic retrieval was not allowed. You can provide this manually.")

    # ------------------------------------------------------------------
    # Retry endpoint security -- same checks as first Auto-Fill (task item 3)
    # ------------------------------------------------------------------
    def test_retry_verifies_application_ownership(self):
        application = self._apply("CITIZEN_6D_010")
        code = application["requirements"][0]["requirementCode"]
        with patch.object(requirement_fulfillment, "select_dependency_provider", return_value={"serviceId": "SVC-1"}), \
             patch.object(requirement_fulfillment, "request_registered_service", return_value=_failure_result()):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_010"))
        with self.assertRaises(HTTPException) as ctx:
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_999"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_retry_verifies_requirement_belongs_to_application(self):
        application = self._apply("CITIZEN_6D_011")
        with self.assertRaises(HTTPException) as ctx:
            auto_fill_requirement(application["appId"], "NOT_A_REAL_REQUIREMENT", AutoFillDecision(decision="ACCEPT"), user=_user("CITIZEN_6D_011"))
        self.assertEqual(ctx.exception.status_code, 404)


class AuditBusThreadSafetyTests(unittest.TestCase):
    """Regression test for a real race Phase 6D's genuine concurrency
    exposed: AuditBus.append() allocated 'sequence' from len(self.entries)
    without a lock, so two concurrent appends (e.g. from two concurrent
    Auto-Fill requests) could compute the same sequence number, which the
    Postgres persistence layer's sequence primary key later rejects --
    turning an otherwise-successful Auto-Fill into a spurious 500."""

    def test_concurrent_appends_never_produce_duplicate_sequence_numbers(self):
        bus = AuditBus()
        errors = []

        def append_many():
            try:
                for _ in range(50):
                    bus.append("SYSTEM", "TEST", "concurrency check", "TEST", "TEST", payload={})
            except Exception as error:  # pragma: no cover
                errors.append(error)

        threads = [threading.Thread(target=append_many) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        sequences = [entry["sequence"] for entry in bus.entries]
        self.assertEqual(len(sequences), len(set(sequences)), "duplicate sequence numbers were allocated under concurrency")
        self.assertEqual(sorted(sequences), list(range(1, len(sequences) + 1)))


if __name__ == "__main__":
    unittest.main()
