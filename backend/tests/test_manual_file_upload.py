"""Manual document upload as a real file (device upload or camera capture):
type/signature/size validation, owner-only preview and download of the
original file, replacement, and removal before submission."""
from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.citizen_routes import (
    ApplySchemeRequest, RequirementUpload, apply_to_scheme, download_requirement_document, get_citizen_application,
    remove_requirement_upload, upload_requirement_document, view_requirement_document,
)
from app.core.persistence import ApplicationRow, CitizenNotificationRow, DocumentRow, Session, engine, get_document
from tests.catalog_fixture import remove_test_vocabulary, seed_test_vocabulary

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.4\n%demo\n"
CODE = "DOMICILE_PROOF"

_VOCABULARY_ADDED: set[str] = set()


def setUpModule():
    _VOCABULARY_ADDED.update(seed_test_vocabulary())


def tearDownModule():
    remove_test_vocabulary(_VOCABULARY_ADDED)


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Upload Test Citizen", "role": "CITIZEN"}


def _file(content_type: str, data: bytes, name: str = "scan.png") -> RequirementUpload:
    return RequirementUpload(title="Domicile certificate", contentType=content_type, content=base64.b64encode(data).decode(), fileName=name)


class ManualFileUploadTests(unittest.TestCase):
    def setUp(self):
        self._app_ids: list[str] = []

    def tearDown(self):
        with Session(engine) as session:
            if self._app_ids:
                session.query(DocumentRow).filter(DocumentRow.app_id.in_(self._app_ids)).delete(synchronize_session=False)
                session.query(CitizenNotificationRow).filter(CitizenNotificationRow.application_id.in_(self._app_ids)).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._app_ids)).delete(synchronize_session=False)
            session.commit()

    def _apply(self, citizen_id: str) -> str:
        application = apply_to_scheme(ApplySchemeRequest(schemeId="SCH-MH-2026"), SimpleNamespace(state=SimpleNamespace()), user=_user(citizen_id))
        self._app_ids.append(application["appId"])
        return application["appId"]

    def test_device_upload_is_stored_and_previewable_as_the_original_file(self):
        app_id = self._apply("CITIZEN_UPF_001")
        result = upload_requirement_document(app_id, CODE, _file("image/png", PNG, "C:\\Users\\me\\my scan.PNG"), user=_user("CITIZEN_UPF_001"))
        self.assertEqual(next(r for r in result["requirements"] if r["requirementCode"] == CODE)["status"], "VALIDATED")
        view = view_requirement_document(app_id, CODE, user=_user("CITIZEN_UPF_001"))
        self.assertTrue(view["isFile"])
        self.assertEqual((view["contentType"], view["fileName"], view["sizeBytes"]), ("image/png", "my-scan.png", len(PNG)))
        self.assertNotIn("fileContent", view)
        download = download_requirement_document(app_id, CODE, user=_user("CITIZEN_UPF_001"))
        self.assertEqual(download.body, PNG)
        self.assertEqual(download.media_type, "image/png")
        self.assertIn('filename="my-scan.png"', download.headers["content-disposition"])
        self.assertNotIn("fileContent", get_document(f"DOC-{app_id}-{CODE}"), "file bytes stay out of ordinary document reads")

    def test_camera_capture_jpeg_is_accepted(self):
        app_id = self._apply("CITIZEN_UPF_002")
        upload_requirement_document(app_id, CODE, _file("image/jpeg", JPEG, "camera-capture.jpg"), user=_user("CITIZEN_UPF_002"))
        self.assertEqual(download_requirement_document(app_id, CODE, user=_user("CITIZEN_UPF_002")).body, JPEG)

    def test_replace_overwrites_the_previous_upload(self):
        app_id = self._apply("CITIZEN_UPF_003")
        upload_requirement_document(app_id, CODE, _file("image/png", PNG), user=_user("CITIZEN_UPF_003"))
        upload_requirement_document(app_id, CODE, _file("application/pdf", PDF, "domicile.pdf"), user=_user("CITIZEN_UPF_003"))
        view = view_requirement_document(app_id, CODE, user=_user("CITIZEN_UPF_003"))
        self.assertEqual((view["contentType"], view["fileName"]), ("application/pdf", "domicile.pdf"))
        self.assertEqual(download_requirement_document(app_id, CODE, user=_user("CITIZEN_UPF_003")).body, PDF)

    def test_unsupported_mismatched_and_oversized_files_are_rejected(self):
        app_id = self._apply("CITIZEN_UPF_004")
        user = _user("CITIZEN_UPF_004")
        cases = [
            ("application/x-msdownload", b"MZ\x90\x00", "Unsupported"),
            ("image/png", b"MZ\x90\x00 renamed executable", "does not match"),
            ("image/jpeg", b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024), "5 MB"),
        ]
        for content_type, data, expected in cases:
            with self.assertRaises(HTTPException) as ctx:
                upload_requirement_document(app_id, CODE, _file(content_type, data), user=user)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertTrue(any(expected in reason for reason in ctx.exception.detail["reasons"]), ctx.exception.detail)
        self.assertIsNone(get_document(f"DOC-{app_id}-{CODE}"))

    def test_removal_before_submission_restores_the_requirement(self):
        app_id = self._apply("CITIZEN_UPF_005")
        user = _user("CITIZEN_UPF_005")
        upload_requirement_document(app_id, CODE, _file("image/png", PNG), user=user)
        result = remove_requirement_upload(app_id, CODE, user=user)
        requirement = next(r for r in result["requirements"] if r["requirementCode"] == CODE)
        self.assertEqual(requirement["status"], "NOT_PROVIDED")
        self.assertNotIn("documentId", requirement)
        self.assertIsNone(get_document(f"DOC-{app_id}-{CODE}"))
        with self.assertRaises(HTTPException) as ctx:
            remove_requirement_upload(app_id, CODE, user=user)
        self.assertEqual(ctx.exception.status_code, 409, "nothing left to remove")

    def test_removal_is_atomic_when_the_document_delete_fails(self):
        app_id = self._apply("CITIZEN_UPF_007")
        user = _user("CITIZEN_UPF_007")
        upload_requirement_document(app_id, CODE, _file("image/png", PNG), user=user)
        with patch("app.api.citizen_routes.delete_document", side_effect=RuntimeError("simulated delete failure")):
            with self.assertRaises(RuntimeError):
                remove_requirement_upload(app_id, CODE, user=user)
        # Neither half was committed: the requirement still references the
        # upload and the document is still there.
        requirement = next(r for r in get_citizen_application(app_id, user=user)["requirements"] if r["requirementCode"] == CODE)
        self.assertEqual(requirement["status"], "VALIDATED")
        self.assertEqual(requirement.get("documentId"), f"DOC-{app_id}-{CODE}")
        self.assertIsNotNone(get_document(f"DOC-{app_id}-{CODE}"))

    def test_only_the_owner_can_view_or_remove_an_upload(self):
        app_id = self._apply("CITIZEN_UPF_006")
        upload_requirement_document(app_id, CODE, _file("image/png", PNG), user=_user("CITIZEN_UPF_006"))
        for call in (view_requirement_document, download_requirement_document, remove_requirement_upload):
            with self.assertRaises(HTTPException) as ctx:
                call(app_id, CODE, user=_user("CITIZEN_UPF_OTHER"))
            self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(get_citizen_application(app_id, user=_user("CITIZEN_UPF_006"))["appId"], app_id)


if __name__ == "__main__":
    unittest.main()


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())
