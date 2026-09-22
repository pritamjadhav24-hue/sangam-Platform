"""Phase 6F2 Task B: Manual Upload availability across every seeded scheme.

The frontend's Upload Manually gate (ApplicationFormPage.jsx) is driven
entirely by each requirement's backend-supplied `dataType` -- generic, not a
per-scheme hardcoded list. This module proves that data actually resolves
correctly, end to end, for every seeded scheme: every DOCUMENT/CERTIFICATE
requirement really does carry that dataType through apply_to_scheme(), and
manual upload actually succeeds for it.

(This is also regression coverage for a real bug found while auditing this
task: RequirementCatalogRow -- the table requirement_data_type() reads -- was
never actually seeded in the running environment, so every requirement
silently fell back to dataType "RECORD" and Upload Manually never appeared
anywhere. Fixed by actually running seed_requirement_catalog() and adding
SANGAM_SEED_CATALOG=true to .env.example.)
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.api.citizen_routes import ApplySchemeRequest, RequirementUpload, apply_to_scheme, upload_requirement_document
from app.core.persistence import ApplicationRow, DocumentRow, RequirementCatalogRow, REQUIREMENT_CATALOG, engine, seed_requirement_catalog
from app.engine.registry import SCHEMES
from types import SimpleNamespace


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace())


DOCUMENT_TYPES = {"DOCUMENT", "CERTIFICATE"}
_CATALOG_BY_CODE = {item["code"]: item for item in REQUIREMENT_CATALOG}


def setUpModule():
    with patch.dict(os.environ, {"SANGAM_SEED_CATALOG": "true"}):
        seed_requirement_catalog()


class ManualUploadCoverageAcrossAllSchemesTest(unittest.TestCase):
    def setUp(self):
        self._created_app_ids: list[str] = []

    def tearDown(self):
        if not self._created_app_ids:
            return
        with Session(engine) as session:
            session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str) -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._created_app_ids.append(application["appId"])
        return application

    def test_requirement_catalog_is_actually_seeded(self):
        with Session(engine) as session:
            self.assertGreater(session.query(RequirementCatalogRow).count(), 0, "RequirementCatalogRow must be seeded for dataType-driven gating to work")

    def test_every_scheme_requirement_reports_its_catalogued_data_type(self):
        """For every scheme, every requirement's dataType as seen by the
        citizen-facing API matches the canonical REQUIREMENT_CATALOG entry --
        not a per-scheme guess, not a default fallback."""
        for index, scheme in enumerate(SCHEMES):
            citizen_id = f"CITIZEN_MU_{index:03d}"
            application = self._apply(citizen_id, scheme["id"])
            for requirement in application["requirements"]:
                expected = _CATALOG_BY_CODE[requirement["requirementCode"]]["dataType"]
                self.assertEqual(requirement["dataType"], expected, (scheme["id"], requirement["requirementCode"]))

    def test_every_document_type_requirement_across_every_scheme_accepts_manual_upload(self):
        """The real assertion behind Task B: for every scheme, every
        DOCUMENT/CERTIFICATE requirement can actually be manually uploaded
        (not merely flagged as document-like)."""
        exercised_document_requirement = False
        for index, scheme in enumerate(SCHEMES):
            citizen_id = f"CITIZEN_MU2_{index:03d}"
            application = self._apply(citizen_id, scheme["id"])
            document_requirements = [item for item in application["requirements"] if item["dataType"] in DOCUMENT_TYPES]
            for requirement in document_requirements:
                exercised_document_requirement = True
                result = upload_requirement_document(
                    application["appId"], requirement["requirementCode"],
                    RequirementUpload(title=f"{requirement['displayLabel']} copy", content="synthetic demo upload content"),
                    user=_user(citizen_id),
                )
                updated = next(item for item in result["requirements"] if item["requirementCode"] == requirement["requirementCode"])
                self.assertEqual(updated["status"], "VALIDATED", (scheme["id"], requirement["requirementCode"]))
        self.assertTrue(exercised_document_requirement, "no scheme exposed a DOCUMENT/CERTIFICATE requirement -- test fixture is stale")

    def test_non_document_requirements_are_not_forced_into_upload_flow(self):
        """Non-document attributes (e.g. IDENTITY, RECORD-type requirements)
        are legitimately Auto-Fill-only -- this is not a gap, per Task B."""
        application = self._apply("CITIZEN_MU_003", "SCH-MH-2026")
        non_document = [item for item in application["requirements"] if item["dataType"] not in DOCUMENT_TYPES]
        self.assertTrue(non_document)
        for requirement in non_document:
            self.assertIn(requirement["dataType"], {"ATTRIBUTE", "RECORD"})


if __name__ == "__main__":
    unittest.main()
