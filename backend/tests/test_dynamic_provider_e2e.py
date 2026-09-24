"""Phase 3 end-to-end test.

requirement -> dynamic provider discovery -> consent validation -> provider
selection -> adapter -> department REST API -> sandbox DB -> response ->
schema mapping -> canonical validated result -> dependency result.

The test starts from a requirement code only. It never tells the engine
which department to use -- the provider name/department that ends up serving
the requirement is read back from select_dependency_provider's own decision,
not asserted as a literal a priori.
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

from tests.catalog_fixture import restore_tables, snapshot_provider_catalog
from app.core.demo_state import reset_demo_state
from app.core.persistence import (
    DEPARTMENT_SANDBOX_PROVIDERS, DepartmentRow, ProviderCapabilityRow, ProviderRow,
    SchemaMappingRow, ServiceCatalogRow, engine, seed_department_sandbox_providers,
    seed_department_sandbox_schema_mappings,
)
from app.engine.adapters import integration_health
from app.engine.consent_manager import create_consent
from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency
from app.engine.registry import select_dependency_provider
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool

TEST_PORT = 18197
CITIZENS = generate_citizen_pool(60)

_server = None
_server_thread = None


_CATALOG_SNAPSHOT: list = []


def setUpModule():
    global _server, _server_thread
    _CATALOG_SNAPSHOT.extend(snapshot_provider_catalog())
    spec = SANDBOXES_BY_KEY["revenue"]
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

    with patch.dict(os.environ, {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true"}):
        seed_department_sandbox_providers()
        seed_department_sandbox_schema_mappings()


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    # Only rows this module added are removed; a demo environment's own
    # department providers and mappings survive the test run.
    restore_tables(_CATALOG_SNAPSHOT)


def _citizen_with_land_record():
    spec = SANDBOXES_BY_KEY["revenue"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        resident = session.query(models.ResidentIndex).join(
            models.LandRecord, models.LandRecord.resident_id == models.ResidentIndex.resident_id
        ).first()
        return resident.citizen_ref


class DynamicProviderEndToEndTest(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def test_requirement_to_canonical_validated_dependency_result(self):
        requirement_code = "LAND_HOLDING"  # the test starts here -- no department is named
        citizen_id = _citizen_with_land_record()

        # 1 + 2: dynamic discovery, driven only by the requirement code.
        selected = select_dependency_provider(requirement_code, integration_health())
        self.assertIsNotNone(selected, "expected a dynamically discovered provider for LAND_HOLDING")

        app = {
            "appId": f"PHASE3-E2E-{citizen_id}",
            "citizenId": citizen_id,
            "status": "WAITING_FOR_DEPENDENCY",
            "dependencyIds": [],
            "dependencies": [],
            "requirements": [{"code": requirement_code, "status": "MISSING"}],
            "entityReviews": [],
            "conflictReviews": [],
            "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
        }

        # 3: consent, using the exact existing versioned-consent mechanism.
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        # Dependency creation resolves the same provider discovery already
        # checked above -- proving the workflow layer uses the same dynamic path.
        dependency = ensure_dependency(app, requirement_code)
        self.assertEqual(dependency["providerId"], selected["providerId"])
        self.assertEqual(dependency["providerService"], selected["serviceId"])

        # 4-7: adapter -> department REST API -> sandbox DB -> response ->
        # schema mapping -> canonical -> validation -> dependency result.
        result = initiate_dependency(citizen_id, app, requirement_code)

        self.assertTrue(result["success"], result)
        self.assertEqual(app["dependencies"][0]["status"], "COMPLETED")
        self.assertIsNotNone(app["dependencies"][0]["resultReference"])

        requirement = next(item for item in app["requirements"] if item["code"] == requirement_code)
        self.assertEqual(requirement["status"], "FOUND")
        # Schema mapping: the department's own "survey_number" field must have
        # been translated to the canonical "landSurveyNumber" name -- proving
        # the department field name was never assumed to equal the canonical one.
        self.assertIn("landSurveyNumber", requirement["canonical"])
        self.assertTrue(requirement["validation"]["valid"], requirement["validation"])

        # The provider that actually served this requirement was never named
        # by this test -- only read back from the dynamic selection decision.
        self.assertEqual(dependency["provider"], selected["provider"])


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
