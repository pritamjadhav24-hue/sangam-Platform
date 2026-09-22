"""Phase 4 end-to-end scenarios for the document retrieval/lifecycle layer.

Scenario 1: requirement -> dynamic provider discovery -> consent -> department
REST API -> synthetic document -> adapter -> schema-mapping normalization ->
document validation -> dependency/workflow result.

Scenario 2: the artifact is unavailable (citizen has no record at the
department) -> the dependency reaches the existing waiting state -> a
synthetic citizen upload, through the backend upload boundary, satisfies the
requirement.

Uses BIRTH_CERTIFICATE (Municipal Health Sandbox), a CERTIFICATE-typed
requirement from the Phase 1 catalog, against a live app.department_api
server -- the same pattern established in Phases 2/3.
"""
from __future__ import annotations

import importlib
import os
import threading
import time
import unittest
from unittest.mock import patch

import uvicorn
from sqlalchemy.orm import Session

from app.core.demo_state import reset_demo_state
from app.core.persistence import (
    DEPARTMENT_SANDBOX_PROVIDERS, DepartmentRow, DocumentRow, ProviderCapabilityRow, ProviderRow,
    SchemaMappingRow, ServiceCatalogRow, engine, get_document, seed_department_sandbox_providers,
    seed_department_sandbox_schema_mappings, seed_requirement_catalog,
)
from app.engine.consent_manager import create_consent
from app.engine.artifact_retrieval import retrieve_artifact, submit_citizen_upload
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool

TEST_PORT = 18196
CITIZENS = generate_citizen_pool(60)

_server = None
_server_thread = None


def _reseed(dept_key: str):
    spec = SANDBOXES_BY_KEY[dept_key]
    models = importlib.import_module(spec.models_module)
    seed = importlib.import_module(spec.seed_module)
    models.Base.metadata.drop_all(models.ENGINE)
    models.Base.metadata.create_all(models.ENGINE)
    with session_scope(models.ENGINE) as session:
        seed.seed(session, CITIZENS)
    return models


def setUpModule():
    global _server, _server_thread
    _reseed("municipal_health")

    from app.department_api.main import app as department_app
    config = uvicorn.Config(department_app, host="127.0.0.1", port=TEST_PORT, log_level="error")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    for _ in range(100):
        if getattr(_server, "started", False):
            break
        time.sleep(0.05)
    os.environ["DEPARTMENT_API_BASE_URL"] = f"http://127.0.0.1:{TEST_PORT}"

    with patch.dict(os.environ, {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true", "SANGAM_SEED_CATALOG": "true"}):
        seed_department_sandbox_providers()
        seed_department_sandbox_schema_mappings()
        seed_requirement_catalog()


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    from app.core.persistence import REQUIREMENT_CATALOG, RequirementCatalogRow
    provider_ids = [item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]
    department_ids = list({item["departmentId"] for item in DEPARTMENT_SANDBOX_PROVIDERS})
    service_ids = [item["serviceId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]
    with Session(engine) as session:
        session.query(DocumentRow).filter(DocumentRow.app_id.like("PHASE4-%")).delete(synchronize_session=False)
        session.query(SchemaMappingRow).filter(SchemaMappingRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
        session.query(ProviderCapabilityRow).filter(ProviderCapabilityRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
        session.query(ServiceCatalogRow).filter(ServiceCatalogRow.service_id.in_(service_ids)).delete(synchronize_session=False)
        session.query(ProviderRow).filter(ProviderRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
        session.query(DepartmentRow).filter(DepartmentRow.department_id.in_(department_ids)).delete(synchronize_session=False)
        session.query(RequirementCatalogRow).filter(RequirementCatalogRow.requirement_code.in_([i["code"] for i in REQUIREMENT_CATALOG])).delete(synchronize_session=False)
        session.commit()


def _citizen_with_birth_certificate():
    spec = SANDBOXES_BY_KEY["municipal_health"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        resident = session.query(models.ResidentIndex).join(
            models.BirthCertificate, models.BirthCertificate.resident_id == models.ResidentIndex.resident_id
        ).first()
        return resident.citizen_ref


def _citizen_without_birth_certificate():
    spec = SANDBOXES_BY_KEY["municipal_health"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        with_cert = {row.resident_id for row in session.query(models.BirthCertificate.resident_id).all()}
        resident = session.query(models.ResidentIndex).filter(~models.ResidentIndex.resident_id.in_(with_cert)).first()
        return resident.citizen_ref if resident else None


def _app(app_id, citizen_id, requirement_code):
    return {
        "appId": app_id, "citizenId": citizen_id, "status": "WAITING_FOR_DEPENDENCY",
        "dependencyIds": [], "dependencies": [], "requirements": [{"code": requirement_code, "status": "MISSING"}],
        "entityReviews": [], "conflictReviews": [],
        "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
    }


class DocumentRetrievalSuccessScenarioTest(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def test_requirement_to_validated_document_result(self):
        citizen_id = _citizen_with_birth_certificate()
        self.assertIsNotNone(citizen_id)
        app = _app("PHASE4-E2E-SUCCESS", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        outcome = retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)

        self.assertTrue(outcome["isDocumentRequirement"])
        self.assertTrue(outcome["dependency"]["success"], outcome)
        document = outcome["document"]
        self.assertIsNotNone(document)
        self.assertEqual(document["status"], "VALIDATED")
        self.assertEqual(document["sourceType"], "DEPARTMENT_PROVIDER")
        self.assertTrue(document["isSynthetic"])
        self.assertIsNotNone(document["referenceUri"])
        self.assertIn("birthRegistrationNumber", document["canonical"])  # schema-mapped field

        persisted = get_document(document["documentId"])
        self.assertEqual(persisted["status"], "VALIDATED")
        self.assertEqual(persisted["appId"], "PHASE4-E2E-SUCCESS")


class DocumentWaitingThenUploadScenarioTest(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def test_missing_artifact_reaches_waiting_state_then_citizen_upload_satisfies_it(self):
        citizen_id = _citizen_without_birth_certificate()
        self.assertIsNotNone(citizen_id, "expected at least one resident with no birth certificate")
        app = _app("PHASE4-E2E-WAITING", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        # Step 1: the department has no record -> waiting state, recoverable.
        outcome = retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        self.assertFalse(outcome["dependency"]["success"])
        document = outcome["document"]
        self.assertEqual(document["status"], "WAITING_FOR_RESPONSE")
        self.assertEqual(app["dependencies"][0]["status"], "WAITING_FOR_DEPENDENCY")
        self.assertIsNone(app["dependencies"][0]["resultReference"])

        # Step 2: a synthetic citizen upload, through the backend upload
        # boundary, satisfies the same requirement.
        upload_result = submit_citizen_upload(app, "BIRTH_CERTIFICATE", citizen_id, {
            "title": "Birth Certificate (citizen-provided copy)",
            "contentType": "text/plain",
            "content": "SYNTHETIC/DEMO upload: citizen-provided birth certificate copy for testing.",
        })

        self.assertEqual(upload_result["status"], "ACCEPTED")
        self.assertEqual(app["dependencies"][0]["status"], "COMPLETED")
        self.assertIsNotNone(app["dependencies"][0]["resultReference"])
        uploaded_document = upload_result["document"]
        self.assertEqual(uploaded_document["documentId"], document["documentId"])  # same reference, recovered
        self.assertEqual(uploaded_document["sourceType"], "CITIZEN_UPLOAD")
        self.assertEqual(uploaded_document["status"], "VALIDATED")
        self.assertIsNotNone(uploaded_document["checksum"])


if __name__ == "__main__":
    unittest.main()
