"""Phase 6B: the dynamic scheme application form's backend boundary.

Route handlers in app.api.citizen_routes are called directly as plain
functions (this codebase has no HTTP test client dependency -- see
test_postgres_persistence.py's own SimpleNamespace-based convention for
faking a Request), bypassing only FastAPI's dependency-injection wiring, not
any application logic.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from unittest.mock import patch

from tests.catalog_fixture import remove_test_vocabulary, seed_test_vocabulary
from app.api.citizen_routes import (
    ApplySchemeRequest, RequirementUpload, apply_to_scheme, auto_fill_requirement,
    get_citizen_application, upload_requirement_document,
)
from app.core.persistence import (
    CitizenNotificationRow,
    REQUIREMENT_CATALOG, ApplicationRow, DocumentRow, RequirementCatalogRow, citizen_service_snapshot, engine,
    seed_requirement_catalog,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _user(citizen_id: str, name: str = "Test Citizen") -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": name, "role": "CITIZEN"}


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace())


_VOCABULARY_ADDED: set[str] = set()


def setUpModule():
    _VOCABULARY_ADDED.update(seed_test_vocabulary())


def tearDownModule():
    remove_test_vocabulary(_VOCABULARY_ADDED)


class DynamicApplicationFormTests(unittest.TestCase):
    def setUp(self):
        self._created_app_ids: list[str] = []

    def tearDown(self):
        if not self._created_app_ids:
            return
        with Session(engine) as session:
            session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(CitizenNotificationRow).filter(CitizenNotificationRow.application_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._created_app_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str, scheme_id: str) -> dict:
        application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), _fake_request(), user=_user(citizen_id))
        self._created_app_ids.append(application["appId"])
        return application

    # 1 + 2: authenticated citizen can create an application, associated with the scheme.
    def test_authenticated_citizen_can_create_an_application_for_a_scheme(self):
        application = self._apply("CITIZEN_001", "SCH-MH-2026")
        self.assertTrue(application["appId"])
        self.assertEqual(application["serviceId"], "SCH-MH-2026")
        self.assertEqual(application["status"], "IN_PROGRESS")

    # 3 + 7: ownership.
    def test_application_belongs_to_the_authenticated_citizen_only(self):
        application = self._apply("CITIZEN_001", "SCH-MH-2026")
        # The owner can read it back.
        fetched = get_citizen_application(application["appId"], user=_user("CITIZEN_001"))
        self.assertEqual(fetched["appId"], application["appId"])
        # A different citizen cannot.
        with self.assertRaises(HTTPException) as ctx:
            get_citizen_application(application["appId"], user=_user("CITIZEN_002"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_citizen_cannot_auto_fill_or_upload_for_another_citizens_application(self):
        application = self._apply("CITIZEN_001", "SCH-MH-2026")
        requirement_code = application["requirements"][0]["requirementCode"]
        with self.assertRaises(HTTPException) as ctx:
            auto_fill_requirement(application["appId"], requirement_code, user=_user("CITIZEN_002"))
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            upload_requirement_document(application["appId"], requirement_code, RequirementUpload(title="x", content="y"), user=_user("CITIZEN_002"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_apply_never_trusts_a_client_supplied_citizen_id(self):
        """ApplySchemeRequest has no citizenId field at all -- proven structurally."""
        fields = ApplySchemeRequest.model_fields
        self.assertNotIn("citizenId", fields)
        self.assertEqual(set(fields), {"schemeId"})

    # 4 + 5: requirements resolved dynamically from scheme metadata; different
    # schemes produce different requirement sets, through the same code path.
    def test_requirements_are_resolved_dynamically_from_scheme_metadata(self):
        scholarship = self._apply("CITIZEN_001", "SCH-MH-2026")
        academic = self._apply("CITIZEN_001", "EDU-ACADEMIC-2026")
        scheme_a = citizen_service_snapshot("SCH-MH-2026")
        scheme_b = citizen_service_snapshot("EDU-ACADEMIC-2026")

        self.assertEqual(
            {item["requirementCode"] for item in scholarship["requirements"]},
            {item["code"] for item in scheme_a["requirements"]},
        )
        self.assertEqual(
            {item["requirementCode"] for item in academic["requirements"]},
            {item["code"] for item in scheme_b["requirements"]},
        )
        self.assertNotEqual(
            {item["requirementCode"] for item in scholarship["requirements"]},
            {item["requirementCode"] for item in academic["requirements"]},
        )
        # Every requirement carries backend-determined dataType/mandatory --
        # not something the frontend invents.
        for item in scholarship["requirements"]:
            self.assertIn("dataType", item)
            self.assertIn("mandatory", item)
            self.assertEqual(item["status"], "NOT_PROVIDED")

    def test_reapplying_to_the_same_open_scheme_resumes_instead_of_duplicating(self):
        first = self._apply("CITIZEN_001", "SCH-MH-2026")
        second = self._apply("CITIZEN_001", "SCH-MH-2026")
        self.assertEqual(first["appId"], second["appId"])
        with Session(engine) as session:
            rows = session.execute(select(ApplicationRow).where(ApplicationRow.citizen_id == "CITIZEN_001")).scalars().all()
        matching = [row for row in rows if row.payload.get("serviceId") == "SCH-MH-2026"]
        self.assertEqual(len(matching), 1, "no duplicate application row should have been created")

    # 6: requirement state is persisted (survives a fresh authoritative read).
    def test_requirement_state_changes_are_persisted_and_recoverable(self):
        application = self._apply("CITIZEN_002", "EDU-ACADEMIC-2026")
        requirement_code = application["requirements"][0]["requirementCode"]

        auto_fill_requirement(application["appId"], requirement_code, user=_user("CITIZEN_002"))

        # Simulate "citizen leaves and returns later": a completely fresh read.
        # This test doesn't set up a live department sandbox server (see
        # test_dynamic_provider_e2e.py for that), so the real Auto-Fill
        # pipeline (Phase 6C) may or may not find a reachable provider here --
        # either way, the attempt itself, and whatever state it produced,
        # must have been durably persisted rather than lost.
        resumed = get_citizen_application(application["appId"], user=_user("CITIZEN_002"))
        resumed_requirement = next(item for item in resumed["requirements"] if item["requirementCode"] == requirement_code)
        self.assertNotEqual(resumed_requirement["status"], "NOT_PROVIDED")

    # 8: manual upload is associated with the correct requirement (and application/citizen).
    def test_manual_upload_is_associated_with_the_correct_application_and_requirement(self):
        application = self._apply("CITIZEN_001", "SCH-MH-2026")
        document_requirement = next(item for item in application["requirements"] if item.get("dataType") in {"DOCUMENT", "CERTIFICATE"})
        code = document_requirement["requirementCode"]

        result = upload_requirement_document(application["appId"], code, RequirementUpload(title="Demo Certificate", contentType="text/plain", content="SYNTHETIC/DEMO test content"), user=_user("CITIZEN_001"))

        updated_requirement = next(item for item in result["requirements"] if item["requirementCode"] == code)
        self.assertEqual(updated_requirement["status"], "VALIDATED")
        self.assertTrue(updated_requirement["documentId"].startswith(f"DOC-{application['appId']}-{code}"))

        from app.core.persistence import get_document
        document = get_document(updated_requirement["documentId"])
        self.assertEqual(document["appId"], application["appId"])
        self.assertEqual(document["requirementCode"], code)
        self.assertEqual(document["citizenId"], "CITIZEN_001")
        self.assertEqual(document["sourceType"], "CITIZEN_UPLOAD")

        # Other requirements on the same application are untouched.
        other = [item for item in result["requirements"] if item["requirementCode"] != code]
        self.assertTrue(all(item["status"] == "NOT_PROVIDED" for item in other))

    def test_manual_upload_is_rejected_for_a_non_document_requirement_type(self):
        application = self._apply("CITIZEN_001", "SCH-MH-2026")
        non_document = next((item for item in application["requirements"] if item.get("dataType") not in {"DOCUMENT", "CERTIFICATE"}), None)
        if non_document is None:
            self.skipTest("no non-document requirement on this scheme to exercise the rejection path")
        with self.assertRaises(HTTPException) as ctx:
            upload_requirement_document(application["appId"], non_document["requirementCode"], RequirementUpload(title="x", content="y"), user=_user("CITIZEN_001"))
        self.assertEqual(ctx.exception.status_code, 400)


class NoHardcodedSchemeRequirementRoutingTests(unittest.TestCase):
    """Requirement 9: no `if scheme == X: return [...]` style hardcoding."""

    def test_apply_route_builds_requirements_only_from_scheme_catalog_data(self):
        source = (BACKEND_ROOT / "app" / "api" / "citizen_routes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        apply_function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "apply_to_scheme")
        body_source = ast.get_source_segment(source, apply_function)
        # No scheme id literal (e.g. "SCH-MH-2026") or requirement code
        # literal (e.g. "DOMICILE_PROOF") appears inside the handler itself --
        # the requirement list comes entirely from citizen_service_snapshot().
        for literal in ("SCH-MH-2026", "EDU-ACADEMIC-2026", "DOMICILE_PROOF", "INCOME_PROOF", "ACADEMIC_RECORD"):
            self.assertNotIn(literal, body_source, f"apply_to_scheme must not hardcode {literal}")
        self.assertIn("citizen_service_snapshot", body_source)
        self.assertIn("requirement_data_type", body_source)


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
