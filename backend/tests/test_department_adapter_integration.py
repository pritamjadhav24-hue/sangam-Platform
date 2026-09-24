"""End-to-end tests: SANGAM's provider/adapter layer talking to a live
app.department_api server, which itself only reads its own sandbox database.

Covers testing requirements 2, 3, 5, 6, 7, 8 from the Phase 2 spec. Requirement
9 (existing tests still pass) is verified by running the full suite, not here.
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
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.catalog_fixture import restore_tables, snapshot_provider_catalog
from app.core.persistence import (
    DEPARTMENT_SANDBOX_PROVIDERS, DepartmentRow, ProviderCapabilityRow, ProviderRow,
    SchemaMappingRow, ServiceCatalogRow, engine, seed_department_sandbox_providers,
    seed_department_sandbox_schema_mappings,
)
from app.engine.adapters import AdapterFactory, request_registered_service
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import citizens_with_persona, generate_citizen_pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CITIZENS = generate_citizen_pool(60)
TEST_PORT = 18198
TEST_BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

_server = None
_server_thread = None


def _reseed(dept_key: str, citizens=CITIZENS):
    spec = SANDBOXES_BY_KEY[dept_key]
    models = importlib.import_module(spec.models_module)
    seed = importlib.import_module(spec.seed_module)
    models.Base.metadata.drop_all(models.ENGINE)
    models.Base.metadata.create_all(models.ENGINE)
    with session_scope(models.ENGINE) as session:
        seed.seed(session, citizens)
    return models


_CATALOG_SNAPSHOT: list = []


def setUpModule():
    global _server, _server_thread
    _CATALOG_SNAPSHOT.extend(snapshot_provider_catalog())
    for dept_key in ("revenue", "transport", "agriculture", "education", "labour"):
        _reseed(dept_key)

    from app.department_api.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="error")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    for _ in range(100):
        if getattr(_server, "started", False):
            break
        time.sleep(0.05)

    os.environ["DEPARTMENT_API_BASE_URL"] = TEST_BASE_URL
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


def _find_citizen_with_record(dept_key: str, model_attr: str, join_model_attr: str, join_fk: str):
    """Small helper: find a citizen_ref that has a row in a department's child table."""
    models = importlib.import_module(SANDBOXES_BY_KEY[dept_key].models_module)
    index_model = getattr(models, model_attr)
    child_model = getattr(models, join_model_attr)
    with session_scope(models.ENGINE) as session:
        row = session.query(index_model).join(child_model, getattr(child_model, join_fk) == getattr(index_model, index_model.__mapper__.primary_key[0].name)).first()
        return row.citizen_ref if row else None


class AdapterHTTPBoundaryTests(unittest.TestCase):
    """Requirement 3: the adapter communicates through the API boundary (real HTTP)."""

    def test_adapter_module_never_imports_sandbox_directly(self):
        tree = ast.parse((BACKEND_ROOT / "app" / "engine" / "adapters.py").read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            offenders.extend(name for name in names if name == "app.sandbox" or name.startswith("app.sandbox."))
        self.assertEqual(offenders, [], "adapters.py must reach department data over HTTP only, never by importing app.sandbox")

    def test_adapter_round_trip_to_live_department_api(self):
        citizen_ref = _find_citizen_with_record("revenue", "ResidentIndex", "LandRecord", "resident_id")
        self.assertIsNotNone(citizen_ref)
        adapter = AdapterFactory.create(
            "Department Sandbox API", "Revenue Sandbox API - Land Records", None,
            provider_id="REVENUE-SANDBOX-LAND",
            config={"environment": "SANDBOX", "authType": "NONE", "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/revenue/land-records/{citizenRef}", "timeoutSeconds": 5, "maxAttempts": 2},
        )
        result = adapter.retrieve({"citizenId": citizen_ref}, correlation_id="test-corr")
        self.assertTrue(result.success, result.metadata)
        self.assertIsNotNone(result.status_code)  # proves an actual HTTP response was received
        self.assertIn("raw", result.record)
        self.assertIn("survey_number", result.record["raw"])


class DepartmentAPINoSangamAccessTests(unittest.TestCase):
    """Requirement 2: the department API cannot require or directly expose
    SANGAM's own database/business logic -- it only ever touches its own
    sandbox models, never app.core (SANGAM's PostgreSQL layer), app.engine,
    or app.api."""

    def test_department_api_package_never_imports_sangam_core_engine_or_api(self):
        offenders = []
        for path in (BACKEND_ROOT / "app" / "department_api").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[:2] == ["app", "core"] or name.split(".")[:2] == ["app", "engine"] or name.split(".")[:2] == ["app", "api"]:
                        offenders.append((str(path.relative_to(BACKEND_ROOT)), name))
        self.assertEqual(offenders, [], f"app.department_api must never reach SANGAM's own DB/business logic: {offenders}")


class SchemaMappingConversionTests(unittest.TestCase):
    """Requirement 5: schema mapping converts department fields to canonical fields."""

    def test_transport_vehicle_number_maps_to_canonical_field(self):
        citizen_ref = _find_citizen_with_record("transport", "ResidentIndex", "VehicleRegistration", "resident_id")
        self.assertIsNotNone(citizen_ref)
        adapter = AdapterFactory.create(
            "Department Sandbox API", "Transport Sandbox API - Vehicle Registration", None,
            provider_id="TRANSPORT-SANDBOX-VEHICLE",
            config={"environment": "SANDBOX", "authType": "NONE", "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/transport/vehicle-registrations/{citizenRef}", "timeoutSeconds": 5, "maxAttempts": 2},
        )
        result = adapter.retrieve({"citizenId": citizen_ref})
        self.assertTrue(result.success)
        self.assertEqual(result.record["canonical"].get("vehicleRegistrationNumber"), result.record["raw"].get("vehicle_number"))


class ProviderErrorHandlingTests(unittest.TestCase):
    """Requirement 6: provider errors and missing data are handled safely (no exceptions)."""

    def test_missing_department_record_is_a_safe_failure_not_an_exception(self):
        adapter = AdapterFactory.create(
            "Department Sandbox API", "Revenue Sandbox API - Land Records", None,
            provider_id="REVENUE-SANDBOX-LAND",
            config={"environment": "SANDBOX", "authType": "NONE", "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/revenue/land-records/{citizenRef}", "timeoutSeconds": 5, "maxAttempts": 1},
        )
        result = adapter.retrieve({"citizenId": "SYN-CIT-DOES-NOT-EXIST"})
        self.assertFalse(result.success)
        self.assertIsNone(result.record)
        self.assertIsNotNone(result.error_category)

    def test_unreachable_department_api_is_a_safe_failure_not_an_exception(self):
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            adapter = AdapterFactory.create(
                "Department Sandbox API", "Revenue Sandbox API - Land Records", None,
                provider_id="REVENUE-SANDBOX-LAND",
                config={"environment": "SANDBOX", "authType": "NONE", "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/revenue/land-records/{citizenRef}", "timeoutSeconds": 1, "maxAttempts": 1},
            )
            result = adapter.retrieve({"citizenId": "SYN-CIT-00001"})
            self.assertFalse(result.success)
            self.assertIn(result.error_category, {"NETWORK_ERROR", "TIMEOUT", "INTERNAL_ERROR"})


class GenericProviderMechanismTests(unittest.TestCase):
    """Requirement 7: multiple departments invoked through the same generic
    provider mechanism (request_registered_service), no per-department code."""

    def test_several_departments_resolve_through_the_same_generic_function(self):
        cases = [
            ("REV-SANDBOX-LAND-001", "LAND_HOLDING", _find_citizen_with_record("revenue", "ResidentIndex", "LandRecord", "resident_id")),
            ("AGR-SANDBOX-FARMER-001", "FARMER_REGISTRATION", _find_citizen_with_record("agriculture", "Farmer", "SchemeRegistration", "farmer_id")),
            ("EDU-SANDBOX-SCHOLARSHIP-001", "SCHOLARSHIP_ELIGIBILITY", _find_citizen_with_record("education", "Student", "ScholarshipEligibility", "student_id")),
        ]
        successes = 0
        for service_id, requirement_code, citizen_ref in cases:
            if not citizen_ref:
                continue
            result = request_registered_service(service_id, citizen_ref, requirement_code=requirement_code, correlation_id="generic-test")
            self.assertIsNotNone(result, f"{service_id} returned no result at all")
            if result.success:
                successes += 1
        self.assertGreaterEqual(successes, 2, "expected the generic mechanism to succeed for multiple distinct departments")


class NoHardcodedRoutingTests(unittest.TestCase):
    """Requirement 8: no hardcoded application-to-department routing was introduced."""

    def test_orchestration_engine_files_contain_no_new_department_literals(self):
        """Provider IDs are the actual routing decision -- which literal
        provider serves something -- and must never appear hardcoded in any
        orchestration/control-flow file. Requirement codes are expected to
        appear in registry.py's SCHEMES catalog data (a scheme legitimately
        declares which canonical requirements it needs; that declaration
        itself is not a routing decision -- WHO serves a requirement is still
        resolved dynamically via select_dependency_provider), so requirement
        codes are checked only against the actual control-flow files."""
        from app.engine.registry import DEPENDENCY_SERVICES
        provider_literals = [item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS]
        # A sandbox provider may be an alternate for a requirement the
        # original in-process catalog already served (INCOME_PROOF); those
        # pre-existing codes are not new department routing.
        pre_existing_codes = {item["requirementCode"] for item in DEPENDENCY_SERVICES}
        requirement_literals = [item["requirementCode"] for item in DEPARTMENT_SANDBOX_PROVIDERS if item["requirementCode"] not in pre_existing_codes]
        control_flow_files = [
            BACKEND_ROOT / "app" / "engine" / "dependency_orchestrator.py",
            BACKEND_ROOT / "app" / "engine" / "workflow_engine.py",
        ]
        all_engine_files = control_flow_files + [BACKEND_ROOT / "app" / "engine" / "registry.py"]
        offenders = []
        for path in all_engine_files:
            text = path.read_text(encoding="utf-8")
            for literal in provider_literals:
                if literal in text:
                    offenders.append((path.name, literal))
        for path in control_flow_files:
            text = path.read_text(encoding="utf-8")
            for literal in requirement_literals:
                if literal in text:
                    offenders.append((path.name, literal))
        self.assertEqual(offenders, [], f"Orchestration code must stay capability-driven, not hardcode new department routing: {offenders}")


if __name__ == "__main__":
    unittest.main()
