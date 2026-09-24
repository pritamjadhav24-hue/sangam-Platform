"""Phase 6F2 Task C: citizen-facing verified document view/download.

No file bytes exist anywhere in this prototype (Auto-Fill produces a
canonical record, not a scanned document) -- so "View"/"Download" render a
citizen-safe text document synthesized purely from the requirement's own
metadata and the document's canonical fields. Provider/department/API/
database internals are never included, and only the owning citizen can ever
reach their own VALIDATED document.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sqlalchemy.orm import Session

from tests.catalog_fixture import non_demo_citizens
from app.api.citizen_routes import (
    ApplySchemeRequest, AutoFillDecision, RequirementUpload, apply_to_scheme, auto_fill_requirement,
    download_requirement_document, upload_requirement_document, view_requirement_document,
)
from app.core.persistence import ApplicationRow, CitizenNotificationRow, CitizenRow, DocumentRow, engine, seed_catalog, seed_requirement_catalog
from fastapi import HTTPException
from types import SimpleNamespace


def _user(citizen_id: str, name: str = "Test Citizen") -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": name, "role": "CITIZEN"}


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace())


import itertools

# See test_identity_auto_fill.py's identical helper for why this doesn't
# always return the same citizen: per-citizen rate limiting can trip across
# a full-suite run if every module reuses one citizen. This module claims
# offsets 15-29.
_citizen_offsets = itertools.count(15)


def _real_citizen_id() -> str:
    with Session(engine) as session:
        row = non_demo_citizens(session).offset(next(_citizen_offsets)).limit(1).first()
        return row.citizen_id


def setUpModule():
    with patch.dict(os.environ, {"SANGAM_SEED_CATALOG": "true"}):
        seed_catalog()
        seed_requirement_catalog()
    # Defensive cleanup: this module's real citizens (offsets 15-29) are
    # shared fixtures across separate full-suite runs -- an interrupted
    # earlier run can leave a leftover application behind.
    with Session(engine) as session:
        offset_citizen_ids = [row.citizen_id for row in non_demo_citizens(session).offset(15).limit(15).all()]
        if offset_citizen_ids:
            session.query(DocumentRow).filter(DocumentRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.query(CitizenNotificationRow).filter(CitizenNotificationRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.commit()


class DocumentViewDownloadTests(unittest.TestCase):
    def setUp(self):
        self._created_app_ids: list[str] = []

    def tearDown(self):
        if not self._created_app_ids:
            return
        with Session(engine) as session:
            session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str = "SCH-MH-2026") -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        if application.get("status") == "SUBMITTED":
            # See test_citizen_notifications.py's identical guard: a stray
            # already-submitted application on this shared real citizen
            # fixture would otherwise make apply_to_scheme's idempotent
            # reuse hand back a locked application.
            with Session(engine) as session:
                session.query(DocumentRow).filter_by(app_id=application["appId"]).delete(synchronize_session=False)
                session.query(ApplicationRow).filter_by(app_id=application["appId"]).delete(synchronize_session=False)
                session.commit()
            application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._created_app_ids.append(application["appId"])
        return application

    def test_view_returns_a_realistic_title_and_no_pending_document_before_auto_fill(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        with self.assertRaises(HTTPException) as ctx:
            view_requirement_document(application["appId"], "DOMICILE_PROOF", user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_view_after_successful_auto_fill_has_a_realistic_name_and_no_internal_details(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        auto_fill_requirement(application["appId"], "DOMICILE_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))

        view = view_requirement_document(application["appId"], "DOMICILE_PROOF", user=_user(citizen_id, name="Sachin Waghmare"))
        self.assertEqual(view["title"], "Maharashtra Domicile Certificate")
        self.assertEqual(view["status"], "VALIDATED")
        self.assertIn("Sachin Waghmare", view["content"])
        for leaked in ("Revenue Department", "State Resident Registry", "REV-MAHA-101", "SRR-IDENTITY-001", "providerId", "sandboxHandler", "sourceRecordId"):
            self.assertNotIn(leaked, view["content"])

    def test_download_returns_a_text_attachment_matching_the_view(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        auto_fill_requirement(application["appId"], "INCOME_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))

        view = view_requirement_document(application["appId"], "INCOME_PROOF", user=_user(citizen_id))
        response = download_requirement_document(application["appId"], "INCOME_PROOF", user=_user(citizen_id))
        self.assertEqual(response.body.decode("utf-8"), view["content"])
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertTrue(response.headers["content-disposition"].endswith('.txt"'))

    def test_manual_upload_becomes_viewable_and_shows_the_citizens_own_content(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        upload_requirement_document(
            application["appId"], "CASTE_PROOF",
            RequirementUpload(title="My caste certificate", content="synthetic demo upload content for caste proof"),
            user=_user(citizen_id),
        )
        view = view_requirement_document(application["appId"], "CASTE_PROOF", user=_user(citizen_id))
        self.assertIn("synthetic demo upload content for caste proof", view["content"])

    def test_attribute_type_requirement_never_has_a_viewable_document(self):
        """IDENTITY is ATTRIBUTE, not DOCUMENT/CERTIFICATE -- no document row
        is ever created for it, so View/Download must 404, not fabricate one."""
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        auto_fill_requirement(application["appId"], "IDENTITY", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        with self.assertRaises(HTTPException) as ctx:
            view_requirement_document(application["appId"], "IDENTITY", user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_citizen_cannot_view_another_citizens_document(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        auto_fill_requirement(application["appId"], "DOMICILE_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        with self.assertRaises(HTTPException) as ctx:
            view_requirement_document(application["appId"], "DOMICILE_PROOF", user=_user("SOME-OTHER-CITIZEN"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_citizen_cannot_download_another_citizens_document(self):
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        auto_fill_requirement(application["appId"], "DOMICILE_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        with self.assertRaises(HTTPException) as ctx:
            download_requirement_document(application["appId"], "DOMICILE_PROOF", user=_user("SOME-OTHER-CITIZEN"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_rejected_requirement_has_no_viewable_document(self):
        """A requirement that failed validation (REJECTED) must not expose a
        document -- only an actually-VALIDATED one is ever viewable."""
        citizen_id = _real_citizen_id()
        application = self._apply(citizen_id)
        with patch("app.engine.requirement_fulfillment.request_registered_service") as retrieve:
            from app.engine.adapters import AdapterResult
            retrieve.return_value = AdapterResult({"annual_income": "-1", "canonical": {"incomeAmount": -1}}, success=True)
            auto_fill_requirement(application["appId"], "INCOME_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        with self.assertRaises(HTTPException) as ctx:
            view_requirement_document(application["appId"], "INCOME_PROOF", user=_user(citizen_id))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_document_display_names_are_realistic_across_document_type_requirements(self):
        from app.engine.artifact_retrieval import document_display_name
        self.assertEqual(document_display_name("Income proof"), "Income Certificate")
        self.assertEqual(document_display_name("Maharashtra domicile"), "Maharashtra Domicile Certificate")
        self.assertEqual(document_display_name("Ration card"), "Ration Card")
        self.assertEqual(document_display_name("Birth certificate"), "Birth Certificate")
        self.assertEqual(document_display_name("Driving licence"), "Driving Licence")


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
