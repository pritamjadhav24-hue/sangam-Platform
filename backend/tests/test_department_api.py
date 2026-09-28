"""Tests for the simulated department REST API layer itself (app.department_api).

These run the real app.department_api ASGI app on a local uvicorn server (no
extra HTTP test client dependency -- plain urllib, matching the rest of this
test suite) to prove each department API can read its own sandbox data, stays
schema-independent from other departments, and handles missing citizens
safely. Adapter-level HTTP round-trip tests live in
test_department_adapter_integration.py.
"""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn

from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool

CITIZENS = generate_citizen_pool(60)
TEST_PORT = 18199
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def _reseed(dept_key: str):
    spec = SANDBOXES_BY_KEY[dept_key]
    models = importlib.import_module(spec.models_module)
    seed = importlib.import_module(spec.seed_module)
    models.Base.metadata.drop_all(models.ENGINE)
    models.Base.metadata.create_all(models.ENGINE)
    with session_scope(models.ENGINE) as session:
        seed.seed(session, CITIZENS)
    return models


def _get(path: str, headers: dict | None = None):
    try:
        with urlopen(Request(f"{BASE_URL}{path}", headers=headers or {}), timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as error:
        return error.code, json.loads(error.read().decode())


_server = None
_server_thread = None


def setUpModule():
    global _server, _server_thread
    from app.department_api.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="error")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    for _ in range(100):
        if getattr(_server, "started", False):
            break
        time.sleep(0.05)


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)


class DepartmentAPIDataAccessTests(unittest.TestCase):
    """Requirement 1: a department API can read its own sandbox data."""

    def test_revenue_land_record_lookup_returns_seeded_data(self):
        models = _reseed("revenue")
        with session_scope(models.ENGINE) as session:
            resident = session.query(models.ResidentIndex).join(
                models.LandRecord, models.LandRecord.resident_id == models.ResidentIndex.resident_id
            ).first()
            self.assertIsNotNone(resident, "expected at least one resident with a land record")
            citizen_ref = resident.citizen_ref
        status, body = _get(f"/departments/revenue/land-records/{citizen_ref}", {"X-Correlation-ID": "corr-1"})
        self.assertEqual(status, 200)
        self.assertTrue(body["synthetic"])
        self.assertIn("disclaimer", body)
        self.assertEqual(body["correlationId"], "corr-1")
        self.assertIn("survey_number", body["data"])

    def test_revenue_income_certificate_lookup_returns_only_issued_certificates(self):
        models = _reseed("revenue")
        with session_scope(models.ENGINE) as session:
            issued = session.query(models.ResidentIndex).join(
                models.IncomeCertificate, models.IncomeCertificate.resident_id == models.ResidentIndex.resident_id
            ).filter(models.IncomeCertificate.status == "ISSUED").first()
            pending = session.query(models.ResidentIndex).join(
                models.IncomeCertificate, models.IncomeCertificate.resident_id == models.ResidentIndex.resident_id
            ).filter(models.IncomeCertificate.status != "ISSUED").first()
            issued_ref, pending_ref = issued.citizen_ref, pending.citizen_ref
        status, body = _get(f"/departments/revenue/income-certificates/{issued_ref}")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ISSUED")
        self.assertIsInstance(body["data"]["annual_income"], float)
        status, body = _get(f"/departments/revenue/income-certificates/{pending_ref}")
        self.assertEqual(status, 404)

    def test_unknown_citizen_returns_not_found_envelope(self):
        _reseed("revenue")
        status, body = _get("/departments/revenue/land-records/SYN-CIT-DOES-NOT-EXIST")
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], "NOT_FOUND")
        self.assertTrue(body["synthetic"])


class DepartmentAPISchemaIndependenceTests(unittest.TestCase):
    """Requirement 4: department-specific schemas/field names remain independent."""

    def test_field_names_differ_across_departments(self):
        revenue_models = _reseed("revenue")
        labour_models = _reseed("labour")

        with session_scope(revenue_models.ENGINE) as session:
            resident = session.query(revenue_models.ResidentIndex).join(
                revenue_models.LandRecord, revenue_models.LandRecord.resident_id == revenue_models.ResidentIndex.resident_id
            ).first()
            revenue_citizen_ref = resident.citizen_ref
        _, revenue_body = _get(f"/departments/revenue/land-records/{revenue_citizen_ref}")

        with session_scope(labour_models.ENGINE) as session:
            worker = session.query(labour_models.RegisteredWorker).join(
                labour_models.EstablishmentRegistration, labour_models.EstablishmentRegistration.worker_id == labour_models.RegisteredWorker.worker_id
            ).first()
            labour_citizen_ref = worker.citizen_ref
        _, labour_body = _get(f"/departments/labour/workers/{labour_citizen_ref}")

        self.assertNotIn("dateOfBirth", revenue_body["data"])
        self.assertIn("dateOfBirth", labour_body["data"])
        self.assertNotIn("occupation", revenue_body["data"])
        self.assertNotEqual(revenue_body["sourceSystem"], labour_body["sourceSystem"])

    def test_endpoints_are_not_forced_into_an_identical_shape(self):
        """Different departments expose genuinely different resources, not a
        copy-pasted generic endpoint set."""
        from app.department_api.main import app
        routes = {route.path for route in app.routes}
        self.assertIn("/departments/revenue/land-records/{citizen_ref}", routes)
        self.assertIn("/departments/municipal-health/immunization-records/{citizen_ref}", routes)
        self.assertIn("/departments/food-civil-supplies/ration-cards/{citizen_ref}", routes)
        revenue_resource_routes = [p for p in routes if p.startswith("/departments/revenue/") and "{citizen_ref}" in p]
        transport_resource_routes = [p for p in routes if p.startswith("/departments/transport/") and "{citizen_ref}" in p]
        # land records, income certificates, domicile certificates
        self.assertEqual(len(revenue_resource_routes), 3)
        self.assertEqual(len(transport_resource_routes), 2)


class DepartmentAPIAuthTests(unittest.TestCase):
    """Provider authentication/configuration boundary demonstration (Transport)."""

    def test_transport_requires_api_key_when_configured(self):
        _reseed("transport")
        with patch.dict(os.environ, {"DEPARTMENT_API_KEY_TRANSPORT": "test-secret"}):
            status, _ = _get("/departments/transport/vehicle-registrations/SYN-CIT-00001")
            self.assertEqual(status, 401)
            status, _ = _get("/departments/transport/vehicle-registrations/SYN-CIT-00001", {"X-API-Key": "test-secret"})
            self.assertIn(status, {200, 404})

    def test_transport_open_when_no_key_configured(self):
        _reseed("transport")
        os.environ.pop("DEPARTMENT_API_KEY_TRANSPORT", None)
        status, _ = _get("/departments/transport/vehicle-registrations/SYN-CIT-00001")
        self.assertIn(status, {200, 404})


if __name__ == "__main__":
    unittest.main()
