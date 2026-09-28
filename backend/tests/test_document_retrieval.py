"""Phase 4: unit-level coverage for the document retrieval/lifecycle layer
(app.engine.artifact_retrieval) that doesn't need the full e2e fixture.
"""
from __future__ import annotations

import ast
import importlib
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import uvicorn
from sqlalchemy.orm import Session

from tests.catalog_fixture import restore_tables, snapshot_provider_catalog
from app.core.demo_state import reset_demo_state
from app.core.persistence import (
    DEPARTMENT_SANDBOX_PROVIDERS, DepartmentRow, DocumentRow, ProviderCapabilityRow, ProviderRow,
    RequirementCatalogRow, SchemaMappingRow, ServiceCatalogRow, engine, seed_department_sandbox_providers,
    seed_department_sandbox_schema_mappings, seed_requirement_catalog,
)
from app.engine.artifact_retrieval import (
    is_document_requirement, requirement_data_type, retrieve_artifact, submit_citizen_upload,
    validate_upload_metadata,
)
from app.engine.consent_manager import ConsentAuthorizationError, create_consent
from app.engine.registry import select_dependency_provider
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_PORT = 18195
CITIZENS = generate_citizen_pool(60)

_server = None
_server_thread = None


_CATALOG_SNAPSHOT: list = []


def setUpModule():
    global _server, _server_thread
    _CATALOG_SNAPSHOT.extend(snapshot_provider_catalog())
    for dept_key in ("municipal_health", "revenue"):
        spec = SANDBOXES_BY_KEY[dept_key]
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
    os.environ["DEPARTMENT_API_BASE_URL"] = f"http://127.0.0.1:{TEST_PORT}"

    with patch.dict(os.environ, {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true", "SANGAM_SEED_CATALOG": "true"}):
        seed_department_sandbox_providers()
        seed_department_sandbox_schema_mappings()
        seed_requirement_catalog()


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    with Session(engine) as session:
        session.query(DocumentRow).filter(DocumentRow.app_id.like("PHASE4-%")).delete(synchronize_session=False)
        session.commit()
    # Put the provider registry and vocabulary back exactly as they were:
    # only rows this module added are removed, so a demo environment's own
    # department providers and vocabulary survive the test run.
    restore_tables(_CATALOG_SNAPSHOT)


def _app(app_id, citizen_id, requirement_code):
    return {
        "appId": app_id, "citizenId": citizen_id, "status": "WAITING_FOR_DEPENDENCY",
        "dependencyIds": [], "dependencies": [], "requirements": [{"code": requirement_code, "status": "MISSING"}],
        "entityReviews": [], "conflictReviews": [],
        "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
    }


class RequirementDataTypeTests(unittest.TestCase):
    def test_document_and_certificate_requirements_are_document_eligible(self):
        self.assertEqual(requirement_data_type("BIRTH_CERTIFICATE"), "CERTIFICATE")
        self.assertTrue(is_document_requirement("BIRTH_CERTIFICATE"))
        self.assertTrue(is_document_requirement("DOMICILE_PROOF"))

    def test_record_and_attribute_requirements_are_not_document_eligible(self):
        self.assertEqual(requirement_data_type("ACADEMIC_RECORD"), "RECORD")
        self.assertFalse(is_document_requirement("ACADEMIC_RECORD"))
        self.assertFalse(is_document_requirement("IDENTITY"))

    def test_uncatalogued_requirement_defaults_to_non_document(self):
        self.assertFalse(is_document_requirement("SOME_REQUIREMENT_NOT_IN_ANY_CATALOG"))


class StructuredRecordRetrievalStillWorksTests(unittest.TestCase):
    """Requirement 1: retrieve_artifact must not assume every requirement is
    a document requirement -- a RECORD requirement keeps behaving exactly
    like Phase 3's initiate_dependency, with no document row created."""

    def setUp(self):
        reset_demo_state()
        from app.engine.adapters import set_integration_availability
        set_integration_availability("Education Department", True)

    def test_structured_requirement_succeeds_with_no_document_reference(self):
        app = _app("PHASE4-STRUCTURED", "CITIZEN_001", "ACADEMIC_RECORD")
        receipt = create_consent("CITIZEN_001", True)
        app["consentId"] = receipt["consentId"]
        outcome = retrieve_artifact(app, "ACADEMIC_RECORD", "CITIZEN_001")
        self.assertFalse(outcome["isDocumentRequirement"])
        self.assertTrue(outcome["dependency"]["success"])
        self.assertIsNone(outcome["document"])


class DocumentMetadataAndSyntheticMarkerTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def _citizen_with_domicile(self):
        spec = SANDBOXES_BY_KEY["revenue"]
        models = importlib.import_module(spec.models_module)
        with session_scope(models.ENGINE) as session:
            resident = session.query(models.ResidentIndex).join(
                models.DomicileCertificate, models.DomicileCertificate.resident_id == models.ResidentIndex.resident_id
            ).filter(models.DomicileCertificate.status == "ISSUED").first()
            return resident.citizen_ref if resident else None

    def test_document_reference_carries_required_metadata_and_synthetic_marker(self):
        citizen_id = self._citizen_with_domicile()
        self.assertIsNotNone(citizen_id)
        app = _app("PHASE4-METADATA", citizen_id, "DOMICILE_PROOF")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]
        outcome = retrieve_artifact(app, "DOMICILE_PROOF", citizen_id)
        document = outcome["document"]
        self.assertIsNotNone(document)
        for field in ("documentId", "appId", "requirementCode", "citizenId", "sourceType", "documentType", "status", "validation"):
            self.assertIn(field, document)
        self.assertTrue(document["isSynthetic"])
        self.assertEqual(document["requirementCode"], "DOMICILE_PROOF")
        self.assertEqual(document["appId"], "PHASE4-METADATA")


class ProviderSelectionAndTrustedFallbackTests(unittest.TestCase):
    """Requirements 5 and 6: source/provider selection is priority-driven,
    generic, and a trusted digital source (lower priority number,
    sourceCategory=TRUSTED_DIGITAL_REPOSITORY) is preferred over a department
    provider when one is configured -- with no new selection algorithm."""

    def test_trusted_source_is_preferred_when_available(self):
        candidates = [
            {"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE4_ARTIFACT", "provider": "Department Provider", "providerId": "DEPT-PROV",
             "requiredService": "X", "serviceName": "X", "serviceId": "SVC-DEPT", "adapter": "Department Sandbox API",
             "priority": 50, "sourceCategory": "DEPARTMENT_PROVIDER"},
            {"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE4_ARTIFACT", "provider": "Trusted Repository", "providerId": "TRUSTED-REPO",
             "requiredService": "X", "serviceName": "X", "serviceId": "SVC-TRUSTED", "adapter": "Department Sandbox API",
             "priority": 1, "sourceCategory": "TRUSTED_DIGITAL_REPOSITORY"},
        ]
        health = [{"system": "Department Provider", "providerId": "DEPT-PROV", "status": "AVAILABLE"},
                  {"system": "Trusted Repository", "providerId": "TRUSTED-REPO", "status": "AVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            selected = select_dependency_provider("PHASE4_ARTIFACT", health)
        self.assertEqual(selected["providerId"], "TRUSTED-REPO")

    def test_falls_back_to_department_provider_when_no_trusted_source_exists(self):
        candidates = [
            {"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE4_ARTIFACT_FALLBACK", "provider": "Department Provider", "providerId": "DEPT-PROV-2",
             "requiredService": "X", "serviceName": "X", "serviceId": "SVC-DEPT-2", "adapter": "Department Sandbox API",
             "priority": 50, "sourceCategory": "DEPARTMENT_PROVIDER"},
        ]
        health = [{"system": "Department Provider", "providerId": "DEPT-PROV-2", "status": "AVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            selected = select_dependency_provider("PHASE4_ARTIFACT_FALLBACK", health)
        self.assertEqual(selected["providerId"], "DEPT-PROV-2")


class UploadValidationTests(unittest.TestCase):
    """Requirement 10: malformed/invalid artifacts are rejected before any
    dependency mutation happens."""

    def setUp(self):
        reset_demo_state()

    def test_missing_content_is_rejected(self):
        self.assertFalse(validate_upload_metadata({"title": "X", "contentType": "text/plain", "content": ""})["valid"])

    def test_unsupported_content_type_is_rejected(self):
        self.assertFalse(validate_upload_metadata({"title": "X", "contentType": "application/pdf", "content": "data"})["valid"])

    def test_oversized_content_is_rejected(self):
        huge = "a" * 300_000
        self.assertFalse(validate_upload_metadata({"title": "X", "contentType": "text/plain", "content": huge})["valid"])

    def test_rejected_upload_never_mutates_the_dependency(self):
        app = _app("PHASE4-UPLOAD-REJECT", "CITIZEN_001", "DOMICILE_PROOF")
        receipt = create_consent("CITIZEN_001", True)
        app["consentId"] = receipt["consentId"]
        result = submit_citizen_upload(app, "DOMICILE_PROOF", "CITIZEN_001", {"title": "", "contentType": "text/plain", "content": ""})
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(app["dependencies"], [])  # ensure_dependency was never even reached


class ProviderUnavailableTests(unittest.TestCase):
    """Requirement 11: an unreachable department API reaches a safe waiting
    state, not an exception, with the error category preserved."""

    def setUp(self):
        reset_demo_state()

    def test_unreachable_department_api_reaches_waiting_state_with_error_category(self):
        app = _app("PHASE4-UNAVAILABLE", "SYN-CIT-00001", "BIRTH_CERTIFICATE")
        receipt = create_consent("SYN-CIT-00001", True)
        app["consentId"] = receipt["consentId"]
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            outcome = retrieve_artifact(app, "BIRTH_CERTIFICATE", "SYN-CIT-00001")
        self.assertFalse(outcome["dependency"]["success"])
        document = outcome["document"]
        self.assertEqual(document["status"], "WAITING_FOR_RESPONSE")
        self.assertIn(document["errorCategory"], {"NETWORK_ERROR", "TIMEOUT", "INTERNAL_ERROR"})


class InvalidConsentTests(unittest.TestCase):
    """Requirement 12: retrieval fails closed on missing consent, and no
    document reference is written for a denied/unauthorized attempt."""

    def setUp(self):
        reset_demo_state()

    def test_missing_consent_fails_closed_and_writes_no_document(self):
        from app.core.persistence import get_document
        app = _app("PHASE4-NO-CONSENT", "CITIZEN_001", "DOMICILE_PROOF")  # no consentId set
        with self.assertRaises(ConsentAuthorizationError):
            retrieve_artifact(app, "DOMICILE_PROOF", "CITIZEN_001")
        self.assertIsNone(get_document(f"DOC-{app['appId']}-DOMICILE_PROOF"))


class NoDirectDepartmentAccessAndNoHardcodedRoutingTests(unittest.TestCase):
    """Requirements 13 and 14."""

    def test_artifact_retrieval_module_never_imports_department_sandboxes(self):
        tree = ast.parse((BACKEND_ROOT / "app" / "engine" / "artifact_retrieval.py").read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            offenders.extend(name for name in names if name == "app.sandbox" or name.startswith("app.sandbox.") or name == "app.department_api" or name.startswith("app.department_api."))
        self.assertEqual(offenders, [], "artifact_retrieval.py must reach department data only through the existing provider/adapter boundary")

    def test_artifact_retrieval_module_contains_no_hardcoded_department_or_provider_literals(self):
        source = (BACKEND_ROOT / "app" / "engine" / "artifact_retrieval.py").read_text(encoding="utf-8")
        forbidden_literals = [item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS] + [
            "Revenue Department", "Education Department", "Social Welfare Department", "Authorized DBT",
        ]
        offenders = [literal for literal in forbidden_literals if literal in source]
        self.assertEqual(offenders, [], f"document retrieval must stay requirement/capability-driven, not department-specific: {offenders}")


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
