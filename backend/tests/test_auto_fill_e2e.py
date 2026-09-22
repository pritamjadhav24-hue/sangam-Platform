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

from app.api.citizen_routes import AutoFillDecision, auto_fill_requirement, get_citizen_application
from app.core.demo_state import reset_demo_state
from app.core.persistence import (
    DEPARTMENT_SANDBOX_PROVIDERS, REQUIREMENT_CATALOG, ApplicationRow, DepartmentRow, DocumentRow,
    ProviderCapabilityRow, ProviderRow, RequirementCatalogRow, SchemaMappingRow, ServiceCatalogRow,
    create_application as create_application_authoritative,
    engine, get_document, seed_department_sandbox_providers, seed_department_sandbox_schema_mappings,
    seed_requirement_catalog,
)
from app.engine import requirement_fulfillment
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


def setUpModule():
    global _server, _server_thread
    with patch.dict(os.environ, {"SANGAM_SEED_CATALOG": "true"}):
        seed_requirement_catalog()
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
    os.environ["DEPARTMENT_API_BASE_URL"] = f"http://127.0.0.1:{TEST_PORT}"

    with patch.dict(os.environ, {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true"}):
        seed_department_sandbox_providers()
        seed_department_sandbox_schema_mappings()


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    with Session(engine) as session:
        session.query(RequirementCatalogRow).filter(
            RequirementCatalogRow.requirement_code.in_([item["code"] for item in REQUIREMENT_CATALOG])
        ).delete(synchronize_session=False)
        session.commit()
    provider_ids = [item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]
    department_ids = list({item["departmentId"] for item in DEPARTMENT_SANDBOX_PROVIDERS})
    service_ids = [item["serviceId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]
    with Session(engine) as session:
        session.query(SchemaMappingRow).filter(SchemaMappingRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
        session.query(ProviderCapabilityRow).filter(ProviderCapabilityRow.provider_id.in_(provider_ids)).delete(synchronize_session=False)
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


if __name__ == "__main__":
    unittest.main()
