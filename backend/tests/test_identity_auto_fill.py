"""Phase 6F2 Task A: IDENTITY requirement Auto-Fill.

IDENTITY was a recognised requirement (REQUIREMENT_CATALOG) with a dormant
canonical-mapping rule (semantic_mapper.map_record), but had no registered
provider capability -- select_dependency_provider("IDENTITY", ...) always
returned None, so Auto-Fill failed for every citizen. The fix adds a sixth
classic-style provider entry (registry.DEPENDENCY_SERVICES) backed by a new
synthetic sandbox handler (app.mocks.identity_registry), picked up by the
existing generic seed_catalog()/select_dependency_provider()/
request_registered_service() machinery -- no requirement-specific branching
anywhere in the Auto-Fill path.

These tests exercise the REAL (unmocked) discovery + adapter + schema
mapping + validation pipeline, mirroring test_auto_fill_e2e.py's "no mocks"
style but for the classic in-process sandbox-handler providers (no live HTTP
server needed for those -- the adapter's SANDBOX environment path calls the
handler function directly).
"""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import Session

from tests.catalog_fixture import remove_test_vocabulary, seed_test_vocabulary
from app.api.citizen_routes import AutoFillDecision, auto_fill_requirement, get_citizen_application, submit_citizen_application
from app.core.persistence import (
    ApplicationRow, CitizenNotificationRow, CitizenRow, DocumentRow, RequirementCatalogRow, REQUIREMENT_CATALOG,
    create_application as create_application_authoritative,
    engine, get_application as get_application_raw, get_document,
    seed_catalog, seed_requirement_catalog,
)
from app.engine import requirement_fulfillment
from app.engine.adapters import integration_health
from app.engine.registry import dependency_registry, select_dependency_provider

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _user(citizen_id: str) -> dict:
    return {"userId": citizen_id, "citizenId": citizen_id, "name": "Test Citizen", "role": "CITIZEN"}


import itertools

# A distinct real citizen per call (not always the same one): auto-fill rate
# limiting is per-citizen, and reusing one citizen across every test in a
# full-suite run can trip it even though each individual test file stays
# well under the limit on its own. Each test-module in this suite that needs
# real citizens claims its own offset range to avoid colliding with others.
_citizen_offsets = itertools.count(0)  # this module claims offsets 0-14


def _real_citizen_id() -> str:
    with Session(engine) as session:
        row = session.query(CitizenRow).order_by(CitizenRow.citizen_id).offset(next(_citizen_offsets)).limit(1).first()
        if row is None:
            raise RuntimeError("no synthetic citizen is seeded -- run seed_platform_citizens() first")
        return row.citizen_id


_VOCABULARY_ADDED: set[str] = set()


def setUpModule():
    with patch.dict(os.environ, {"SANGAM_SEED_CATALOG": "true"}):
        seed_catalog()
    _VOCABULARY_ADDED.update(seed_test_vocabulary())
    # Defensive cleanup: this module's real citizens (offsets 0-14) are
    # shared fixtures across separate full-suite runs -- an interrupted
    # earlier run can leave a leftover application behind.
    with Session(engine) as session:
        offset_citizen_ids = [row.citizen_id for row in session.query(CitizenRow).order_by(CitizenRow.citizen_id).offset(0).limit(15).all()]
        if offset_citizen_ids:
            session.query(DocumentRow).filter(DocumentRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.query(ApplicationRow).filter(ApplicationRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.query(CitizenNotificationRow).filter(CitizenNotificationRow.citizen_id.in_(offset_citizen_ids)).delete(synchronize_session=False)
            session.commit()


def tearDownModule():
    remove_test_vocabulary(_VOCABULARY_ADDED)


class IdentityProviderDiscoveryTests(unittest.TestCase):
    def test_identity_has_a_registered_available_provider(self):
        health = integration_health()
        registry = dependency_registry(health)
        identity_entries = [item for item in registry if item["requirementCode"] == "IDENTITY"]
        self.assertEqual(len(identity_entries), 1, registry)
        self.assertEqual(identity_entries[0]["healthStatus"], "AVAILABLE")

    def test_select_dependency_provider_finds_identity(self):
        selected = select_dependency_provider("IDENTITY", integration_health())
        self.assertIsNotNone(selected)
        self.assertEqual(selected["requirementCode"], "IDENTITY")

    def test_existing_classic_requirements_are_unaffected(self):
        health = integration_health()
        registry = dependency_registry(health)
        codes = {item["requirementCode"] for item in registry}
        for code in ("INCOME_PROOF", "CASTE_PROOF", "DOMICILE_PROOF", "ACADEMIC_RECORD", "BANK_DETAILS"):
            self.assertIn(code, codes)


class IdentityAutoFillEndToEndTest(unittest.TestCase):
    """Real (unmocked) discovery + adapter + schema mapping + validation."""

    def setUp(self):
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
            "citizenId": citizen_id, "serviceId": "PHASE6F2-IDENTITY-TEST", "status": "IN_PROGRESS",
            "requirements": requirements,
        })
        self._created_app_ids.append(application["appId"])
        return application

    def test_identity_auto_fill_succeeds_for_a_real_synthetic_citizen(self):
        citizen_id = _real_citizen_id()
        application = self._create_app(citizen_id, [
            {"code": "IDENTITY", "label": "Identity", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "ATTRIBUTE"},
        ])
        result = auto_fill_requirement(application["appId"], "IDENTITY", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == "IDENTITY")
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES, requirement)
        self.assertEqual(requirement["userAction"], "No action required")

    def test_identity_canonical_mapping_and_validation(self):
        citizen_id = _real_citizen_id()
        application = self._create_app(citizen_id, [
            {"code": "IDENTITY", "label": "Identity", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "ATTRIBUTE"},
        ])
        auto_fill_requirement(application["appId"], "IDENTITY", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        internal = requirement_fulfillment.find_requirement(get_application_raw(application["appId"]), "IDENTITY")
        self.assertEqual(internal["canonical"].get("identityStatus"), "VERIFIED")
        self.assertIn("sourceRecordId", internal["canonical"])
        self.assertTrue(internal["validation"]["valid"])

    def test_identity_is_an_attribute_not_a_document_no_document_row_created(self):
        citizen_id = _real_citizen_id()
        application = self._create_app(citizen_id, [
            {"code": "IDENTITY", "label": "Identity", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "ATTRIBUTE"},
        ])
        auto_fill_requirement(application["appId"], "IDENTITY", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        self.assertIsNone(get_document(f"DOC-{application['appId']}-IDENTITY"))

    def test_identity_plus_domicile_on_one_application_and_submit(self):
        """Task A's required combined scenario: IDENTITY + at least one other
        requirement on the same application, both Auto-Filled, application
        becomes submittable."""
        citizen_id = _real_citizen_id()
        application = self._create_app(citizen_id, [
            {"code": "IDENTITY", "label": "Identity", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "ATTRIBUTE"},
            {"code": "DOMICILE_PROOF", "label": "Domicile", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])
        for code in ("IDENTITY", "DOMICILE_PROOF"):
            auto_fill_requirement(application["appId"], code, AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))

        review = get_citizen_application(application["appId"], user=_user(citizen_id))
        by_code = {item["requirementCode"]: item for item in review["requirements"]}
        self.assertIn(by_code["IDENTITY"]["status"], requirement_fulfillment.SUCCESS_STATUSES, by_code["IDENTITY"])
        self.assertIn(by_code["DOMICILE_PROOF"]["status"], requirement_fulfillment.SUCCESS_STATUSES, by_code["DOMICILE_PROOF"])
        self.assertIsNotNone(get_document(f"DOC-{application['appId']}-DOMICILE_PROOF"))
        self.assertTrue(review["readyForSubmission"], review)

        submitted = submit_citizen_application(application["appId"], user=_user(citizen_id))
        self.assertEqual(submitted["status"], "SUBMITTED")

    def test_income_proof_still_succeeds_for_a_real_synthetic_citizen(self):
        """Regression: the classic providers must still work after adding
        IDENTITY, including for a real (non-CITIZEN_001) synthetic citizen --
        this is what actually made Income/Domicile 'succeed' claims true for
        every demo persona, not just the legacy fixture citizen."""
        citizen_id = _real_citizen_id()
        application = self._create_app(citizen_id, [
            {"code": "INCOME_PROOF", "label": "Income", "mandatory": True, "status": "NOT_PROVIDED", "dataType": "CERTIFICATE"},
        ])
        result = auto_fill_requirement(application["appId"], "INCOME_PROOF", AutoFillDecision(decision="ACCEPT"), user=_user(citizen_id))
        requirement = next(item for item in result["requirements"] if item["requirementCode"] == "INCOME_PROOF")
        self.assertIn(requirement["status"], requirement_fulfillment.SUCCESS_STATUSES, requirement)


class NoHardcodedIdentityProviderTests(unittest.TestCase):
    def test_no_provider_or_department_literal_in_auto_fill_route(self):
        source = (BACKEND_ROOT / "app" / "api" / "citizen_routes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "auto_fill_requirement")
        body_source = ast.get_source_segment(source, function)
        for literal in ("State Resident Registry", "identity_verify", "SRR-IDENTITY-001", "IDENTITY ==", '== "IDENTITY"'):
            self.assertNotIn(literal, body_source)

    def test_no_provider_literal_in_requirement_fulfillment(self):
        source = (BACKEND_ROOT / "app" / "engine" / "requirement_fulfillment.py").read_text(encoding="utf-8")
        for literal in ("State Resident Registry", "identity_verify", "SRR-IDENTITY-001"):
            self.assertNotIn(literal, source)


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
