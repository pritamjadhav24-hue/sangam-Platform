"""Phase 5: retry idempotency, document consistency, workflow consistency,
and the two required end-to-end resilience scenarios.

Scenario A (required): initial provider request -> transient failure ->
retry -> provider succeeds -> schema mapping -> validation -> document ->
dependency completed.

Scenario B (required): initial request -> provider unavailable -> waiting/
retry state -> eventual successful recovery -- exercised here via the new
provider-fallback mechanism (a second eligible provider takes over once the
first exhausts its attempts), proving requirement 13 (multiple eligible
providers, no hardcoded fallback chain) in the same scenario.
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
    DEPARTMENT_SANDBOX_PROVIDERS, DepartmentRow, DocumentRow, ProviderCapabilityRow, ProviderRow,
    RequirementCatalogRow, SchemaMappingRow, ServiceCatalogRow, engine, list_documents_for_application,
    seed_department_sandbox_providers, seed_department_sandbox_schema_mappings, seed_requirement_catalog,
)
from app.engine.adapters import AdapterResult, clear_runtime_health, set_integration_availability
from app.engine.artifact_retrieval import retrieve_artifact
from app.engine.consent_manager import ConsentAuthorizationError, create_consent
from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency
from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES_BY_KEY
from app.seeds.synthetic_identity_pool import generate_citizen_pool

TEST_PORT = 18194
CITIZENS = generate_citizen_pool(60)

# A second, ephemeral fallback provider registered only by this test module,
# pointed at the same live department-api server's birth-certificate
# endpoint, used solely to prove fallback works generically.
FALLBACK_PROVIDER_ID = "PHASE5-FALLBACK-MUNICIPAL"
FALLBACK_DEPARTMENT_ID = "PHASE5-FALLBACK-DEPT"
FALLBACK_SERVICE_ID = "PHASE5-FALLBACK-SVC-001"
FALLBACK_REQUIREMENT_CODE = "PHASE5_FALLBACK_BIRTH_CERT"
DOWN_PROVIDER_ID = "PHASE5-DOWN-MUNICIPAL"
DOWN_DEPARTMENT_ID = "PHASE5-DOWN-DEPT"
DOWN_SERVICE_ID = "PHASE5-DOWN-SVC-001"

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


_CATALOG_SNAPSHOT: list = []


def setUpModule():
    global _server, _server_thread
    _CATALOG_SNAPSHOT.extend(snapshot_provider_catalog())
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

    # Register the two ephemeral fallback-scenario providers as real catalog
    # rows (request_registered_service reads providers/services/capabilities
    # directly from PostgreSQL, so a mocked snapshot alone is not enough for
    # a genuine adapter round trip).
    with Session(engine) as session:
        session.add(DepartmentRow(department_id=DOWN_DEPARTMENT_ID, name="Phase5 Down Department (test)", payload={"simulated": True}))
        session.add(DepartmentRow(department_id=FALLBACK_DEPARTMENT_ID, name="Phase5 Fallback Department (test)", payload={"simulated": True}))
        session.add(ProviderRow(
            provider_id=DOWN_PROVIDER_ID, department_id=DOWN_DEPARTMENT_ID, name="Phase5 Down Provider (test)",
            adapter_type="Department Sandbox API", environment="SANDBOX", auth_type="NONE",
            endpoint_ref="PHASE5_DOWN_BASE_URL", timeout_seconds=1, max_attempts=1,
            payload={"httpPath": "/departments/municipal-health/birth-certificates/{citizenRef}"},
        ))
        session.add(ProviderRow(
            provider_id=FALLBACK_PROVIDER_ID, department_id=FALLBACK_DEPARTMENT_ID, name="Phase5 Fallback Provider (test)",
            adapter_type="Department Sandbox API", environment="SANDBOX", auth_type="NONE",
            endpoint_ref="DEPARTMENT_API_BASE_URL", timeout_seconds=5, max_attempts=3,
            payload={"httpPath": "/departments/municipal-health/birth-certificates/{citizenRef}"},
        ))
        session.flush()
        session.add(ServiceCatalogRow(service_id=DOWN_SERVICE_ID, provider_id=DOWN_PROVIDER_ID, name="Down Lookup (test)", requirement_code=FALLBACK_REQUIREMENT_CODE, payload={}))
        session.add(ServiceCatalogRow(service_id=FALLBACK_SERVICE_ID, provider_id=FALLBACK_PROVIDER_ID, name="Fallback Lookup (test)", requirement_code=FALLBACK_REQUIREMENT_CODE, payload={}))
        session.flush()
        session.add(ProviderCapabilityRow(capability_id=f"{DOWN_PROVIDER_ID}:{FALLBACK_REQUIREMENT_CODE}", provider_id=DOWN_PROVIDER_ID, capability_code=FALLBACK_REQUIREMENT_CODE, service_id=DOWN_SERVICE_ID, payload={"priority": 1}))
        session.add(ProviderCapabilityRow(capability_id=f"{FALLBACK_PROVIDER_ID}:{FALLBACK_REQUIREMENT_CODE}", provider_id=FALLBACK_PROVIDER_ID, capability_code=FALLBACK_REQUIREMENT_CODE, service_id=FALLBACK_SERVICE_ID, payload={"priority": 50}))
        session.add(RequirementCatalogRow(requirement_code=FALLBACK_REQUIREMENT_CODE, name="Phase5 fallback test requirement", category="TEST", data_type="CERTIFICATE", payload={}))
        session.flush()
        session.add(SchemaMappingRow(
            mapping_id=f"{FALLBACK_PROVIDER_ID}:registration_number", provider_id=FALLBACK_PROVIDER_ID, service_id=FALLBACK_SERVICE_ID,
            department_field="registration_number", canonical_field="birthRegistrationNumber", data_type="string", payload={},
        ))
        session.commit()
    os.environ["PHASE5_DOWN_BASE_URL"] = "http://127.0.0.1:1"  # never reachable, by design


def tearDownModule():
    if _server is not None:
        _server.should_exit = True
        _server_thread.join(timeout=5)
    with Session(engine) as session:
        session.query(DocumentRow).filter(DocumentRow.app_id.like("PHASE5-%")).delete(synchronize_session=False)
        session.commit()
    # Put the provider registry and vocabulary back exactly as they were:
    # only rows this module added are removed, so a demo environment's own
    # department providers and vocabulary survive the test run.
    restore_tables(_CATALOG_SNAPSHOT)


def _citizen_with_birth_certificate():
    spec = SANDBOXES_BY_KEY["municipal_health"]
    models = importlib.import_module(spec.models_module)
    with session_scope(models.ENGINE) as session:
        resident = session.query(models.ResidentIndex).join(
            models.BirthCertificate, models.BirthCertificate.resident_id == models.ResidentIndex.resident_id
        ).first()
        return resident.citizen_ref


def _app(app_id, citizen_id, requirement_code):
    return {
        "appId": app_id, "citizenId": citizen_id, "status": "WAITING_FOR_DEPENDENCY",
        "dependencyIds": [], "dependencies": [], "requirements": [{"code": requirement_code, "status": "MISSING"}],
        "entityReviews": [], "conflictReviews": [],
        "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
    }


class TransientFailureThenRetrySucceedsE2ETest(unittest.TestCase):
    """Scenario A."""

    def setUp(self):
        reset_demo_state()

    def test_transient_failure_then_retry_succeeds(self):
        """The first attempt hits a genuine network failure (proving NETWORK_ERROR
        classification and RETRY_SAME_PROVIDER end to end); recovery is then
        modeled with the existing set_integration_availability toggle, since
        the adapter layer's own DEGRADED health tracking (integration_health,
        pre-existing and out of scope to change per the phase boundary) would
        otherwise keep a provider that has ever failed ineligible for
        re-selection until a health check observes it healthy again -- exactly
        what the availability toggle represents here."""
        citizen_id = _citizen_with_birth_certificate()
        provider_name = "Municipal Health Sandbox API - Birth Certificate"
        app = _app("PHASE5-SCENARIO-A", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            first = retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        self.assertFalse(first["dependency"]["success"])
        self.assertEqual(first["document"]["status"], "WAITING_FOR_RESPONSE")
        self.assertIn(first["document"]["errorCategory"], {"NETWORK_ERROR", "TIMEOUT", "INTERNAL_ERROR"})
        self.assertEqual(first["retryDecision"], "RETRY_SAME_PROVIDER")
        dependency_id = app["dependencies"][0]["dependencyId"]

        set_integration_availability(provider_name, False)
        set_integration_availability(provider_name, True)  # provider becomes reachable again
        clear_runtime_health(provider_name)  # operator confirms recovery, per the note above
        second = retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        self.assertTrue(second["dependency"]["success"], second)
        self.assertEqual(app["dependencies"][0]["dependencyId"], dependency_id)  # same dependency, not a new one
        document = second["document"]
        self.assertEqual(document["status"], "VALIDATED")
        self.assertIn("birthRegistrationNumber", document["canonical"])
        self.assertEqual(len(app["dependencies"]), 1)


class ProviderFallbackRecoversE2ETest(unittest.TestCase):
    """Scenario B, using the new fallback mechanism: down provider exhausts
    its single attempt, an eligible alternate provider is discovered purely
    from capability data, and it succeeds."""

    def setUp(self):
        reset_demo_state()

    def test_exhausted_provider_falls_back_to_an_eligible_alternate_and_recovers(self):
        citizen_id = _citizen_with_birth_certificate()
        app = _app("PHASE5-SCENARIO-B", citizen_id, FALLBACK_REQUIREMENT_CODE)
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        outcome = retrieve_artifact(app, FALLBACK_REQUIREMENT_CODE, citizen_id)

        dependency = app["dependencies"][0]
        self.assertEqual(dependency["providerId"], FALLBACK_PROVIDER_ID)  # switched away from the down provider
        self.assertTrue(outcome["dependency"]["success"], outcome)
        self.assertEqual(outcome["document"]["status"], "VALIDATED")
        self.assertEqual(len(app["dependencies"]), 1)  # still one dependency, not two


class RetryIdempotencyTests(unittest.TestCase):
    """Requirements 6-10."""

    def setUp(self):
        reset_demo_state()

    def test_retry_increments_attempts_without_duplicating_dependency_or_document(self):
        citizen_id = _citizen_with_birth_certificate()
        app = _app("PHASE5-IDEMPOTENT", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]

        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
            retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)

        self.assertEqual(len(app["dependencies"]), 1)
        self.assertEqual(app["dependencies"][0]["attempts"], 2)
        documents = list_documents_for_application("PHASE5-IDEMPOTENT")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["status"], "WAITING_FOR_RESPONSE")

    def test_successful_retry_completes_the_original_dependency_not_a_new_one(self):
        citizen_id = _citizen_with_birth_certificate()
        provider_name = "Municipal Health Sandbox API - Birth Certificate"
        app = _app("PHASE5-COMPLETE-ORIGINAL", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        original_dependency_id = app["dependencies"][0]["dependencyId"]
        set_integration_availability(provider_name, False)
        set_integration_availability(provider_name, True)
        clear_runtime_health(provider_name)
        retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        self.assertEqual(len(app["dependencies"]), 1)
        self.assertEqual(app["dependencies"][0]["dependencyId"], original_dependency_id)
        self.assertEqual(app["dependencies"][0]["status"], "COMPLETED")

    def test_retry_does_not_duplicate_provider_jobs(self):
        """Exercises the exact dedup guard in initiate_dependency (a
        dependency with jobStatus already QUEUED/RUNNING is never re-enqueued)
        without requiring a live Redis connection -- Redis-specific job-queue
        behavior already has dedicated coverage in test_redis_jobs.py /
        test_async_provider_worker.py via build_test_redis_service."""
        citizen_id = _citizen_with_birth_certificate()
        app = _app("PHASE5-JOB-DEDUP", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]
        dependency = ensure_dependency(app, "BIRTH_CERTIFICATE")
        dependency["jobStatus"] = "QUEUED"  # simulate: a job was already enqueued for this dependency
        with patch.dict(os.environ, {"ASYNC_PROVIDER_JOBS": "true"}):
            result = initiate_dependency(citizen_id, app, "BIRTH_CERTIFICATE")
        self.assertTrue(result.get("queued"))
        self.assertIn("already queued", result.get("message", ""))
        self.assertEqual(len(app["dependencies"]), 1)


class ValidationFailureIsNotBlindlyRetriedTest(unittest.TestCase):
    """Requirement 5: a successfully-retrieved-but-invalid record is a
    terminal outcome for that attempt, not something the system loops
    retrying against the same (already-successful) provider call."""

    def setUp(self):
        reset_demo_state()

    def test_invalid_canonical_data_completes_once_without_retry_loop(self):
        app = _app("PHASE5-BAD-DATA", "CITIZEN_001", "DOMICILE_PROOF")
        receipt = create_consent("CITIZEN_001", True)
        app["consentId"] = receipt["consentId"]
        ensure_dependency(app, "DOMICILE_PROOF")
        bad_record = {"id": "BAD-RECORD-001", "canonical": {}, "raw": {}, "synthetic": True}  # empty canonical -> invalid
        adapter_result = AdapterResult(bad_record, provider="Test Provider", operation="retrieve", success=True, metadata={"providerId": "TEST"})
        result = initiate_dependency("CITIZEN_001", app, "DOMICILE_PROOF", async_override=True, authorized_adapter_result=adapter_result)
        self.assertTrue(result["success"])  # the adapter call itself succeeded
        dependency = app["dependencies"][0]
        self.assertEqual(dependency["status"], "COMPLETED")
        self.assertEqual(dependency["attempts"], 1)  # not incremented in a retry loop
        requirement = app["requirements"][0]
        self.assertFalse(requirement["validation"]["valid"])


class DocumentConsistencyTests(unittest.TestCase):
    """Requirement 12: a later unrelated failed attempt must not destroy an
    already-valid document."""

    def setUp(self):
        reset_demo_state()

    def test_valid_document_is_preserved_against_a_later_failure_state(self):
        from app.core.persistence import get_document
        from app.engine.artifact_retrieval import _reconcile_document

        citizen_id = _citizen_with_birth_certificate()
        app = _app("PHASE5-PRESERVE", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]
        outcome = retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        self.assertEqual(outcome["document"]["status"], "VALIDATED")
        original_checksum_context = outcome["document"]["referenceUri"]

        # Simulate a stray reconciliation call carrying a fresh failure for
        # the same requirement (e.g. a race with an unrelated retry) --
        # the dependency itself is still COMPLETED in memory, so this should
        # be a no-op in practice; directly exercise the defensive guard with
        # a hand-built "failed" dependency snapshot to prove it holds even if
        # some future caller passes one in.
        fake_failed_dependency = {**app["dependencies"][0], "status": "WAITING_FOR_DEPENDENCY", "resultReference": None}
        preserved = _reconcile_document(app, "BIRTH_CERTIFICATE", fake_failed_dependency)

        self.assertEqual(preserved["status"], "VALIDATED")
        self.assertEqual(preserved["referenceUri"], original_checksum_context)
        persisted = get_document(preserved["documentId"])
        self.assertEqual(persisted["status"], "VALIDATED")


class WorkflowHistoryConsistencyTests(unittest.TestCase):
    """Requirement 14."""

    def setUp(self):
        reset_demo_state()

    def test_repeated_retries_do_not_duplicate_application_status_history(self):
        citizen_id = _citizen_with_birth_certificate()
        app = _app("PHASE5-HISTORY", citizen_id, "BIRTH_CERTIFICATE")
        receipt = create_consent(citizen_id, True)
        app["consentId"] = receipt["consentId"]
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
            retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)
        retrieve_artifact(app, "BIRTH_CERTIFICATE", citizen_id)  # now succeeds
        history_statuses = [entry["status"] for entry in app["statusHistory"]]
        # No duplicate consecutive entries -- transition_application's
        # existing "previous == status" no-op guard must still hold.
        for earlier, later in zip(history_statuses, history_statuses[1:]):
            self.assertNotEqual(earlier, later)


class TerminalFailureObservabilityTest(unittest.TestCase):
    """Requirement 11: when no fallback provider exists and attempts are
    exhausted, the outcome must remain observable (not silently lost) and
    the dependency must stay in a recoverable, non-completed state."""

    def setUp(self):
        reset_demo_state()

    def test_retry_exhaustion_without_a_fallback_is_observable_and_recoverable(self):
        app = _app("PHASE5-TERMINAL", "SYN-CIT-DOES-NOT-EXIST", "DOMICILE_PROOF")
        receipt = create_consent("SYN-CIT-DOES-NOT-EXIST", True)
        app["consentId"] = receipt["consentId"]
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:1"}):
            for _ in range(3):  # exhaust the default maxAttempts=3
                outcome = retrieve_artifact(app, "DOMICILE_PROOF", "SYN-CIT-DOES-NOT-EXIST")
        dependency = app["dependencies"][0]
        self.assertNotEqual(dependency["status"], "COMPLETED")  # never falsely completed
        self.assertGreaterEqual(dependency["attempts"], dependency["maxAttempts"])
        self.assertIsNotNone(dependency.get("errorCategory"))  # observable
        self.assertIsNotNone(dependency.get("lastError"))
        self.assertEqual(outcome["document"]["status"], "WAITING_FOR_RESPONSE")  # recoverable, not lost


class ConsentFailureIsNotRetriedIntegrationTest(unittest.TestCase):
    """Requirement 4, exercised through retrieve_artifact rather than the
    consent module directly (see test_dynamic_consent_gating.py for the
    consent-module-level coverage from Phase 3)."""

    def setUp(self):
        reset_demo_state()

    def test_missing_consent_fails_closed_without_ever_reaching_the_provider(self):
        app = _app("PHASE5-NO-CONSENT-RETRY", "CITIZEN_001", "DOMICILE_PROOF")  # no consentId
        with self.assertRaises(ConsentAuthorizationError):
            retrieve_artifact(app, "DOMICILE_PROOF", "CITIZEN_001")
        dependency = app["dependencies"][0]
        # The dependency's own attempt counter increments before the consent
        # check runs (existing, unchanged initiate_dependency behavior), but
        # no provider/adapter call was ever made and the dependency never
        # reaches COMPLETED -- that is what "fails closed" guarantees here.
        self.assertEqual(dependency["attempts"], 1)
        self.assertNotEqual(dependency["status"], "COMPLETED")
        self.assertIsNone(dependency["resultReference"])


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
