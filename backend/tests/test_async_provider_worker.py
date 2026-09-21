import os
import json
import threading
import time
import unittest
from unittest.mock import patch

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.event_bus import event_bus
from app.core.notification_manager import notification_manager
from app.core.persistence import persist_state
from app.core.redis_service import MemoryRedis, build_test_redis_service
from app.engine.adapters import set_integration_availability
from app.engine.consent_manager import CONSUMER, PURPOSE, ConsentAuthorizationError, authorize_persisted_access, create_consent, execute_with_persisted_authorization, revoke_consent
from app.engine.dependency_orchestrator import ensure_domicile_dependency, initiate_domicile
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import create_application
from app.mocks.identity_provider import CITIZENS
from app.core.job_queue import JobQueue
from app.worker import run_once


class AsyncProviderWorkerTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        set_integration_availability("Revenue Department", True)
        self.memory = MemoryRedis()
        self.redis = build_test_redis_service(self.memory)
        self.patches = [
            patch.dict(os.environ, {"ASYNC_PROVIDER_JOBS": "true"}),
            patch("app.core.redis_service.RedisService", lambda enabled=True: self.redis),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        reset_demo_state()
        persist_state()

    def test_provider_operation_is_durable_queued_claimed_and_completed(self):
        citizen_id = "CITIZEN_001"
        receipt = create_consent(citizen_id, True)
        persist_state()
        result = discover(CITIZENS[citizen_id])
        app = create_application(citizen_id, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        dependency = ensure_domicile_dependency(app)
        queued = initiate_domicile(citizen_id, app)
        self.assertTrue(queued["queued"])
        self.assertEqual(dependency["jobStatus"], "QUEUED")
        self.assertNotIn("citizenId", json.loads(self.memory.lists["sangam:jobs"][0])["payload"])
        self.assertEqual(json.loads(self.memory.lists["sangam:jobs"][0])["payload"]["consentId"], receipt["consentId"])
        completed = run_once(JobQueue(self.redis), {})
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(dependency["status"], "COMPLETED")
        self.assertEqual(dependency["jobStatus"], "COMPLETED")
        self.assertEqual(completed["correlationId"], app["appId"])
        self.assertEqual(len([event for event in event_bus.events if event["type"] == "DEPENDENCY_RESOLVED"]), 1)
        self.assertTrue(notification_manager.notifications)
        self.assertTrue(audit_bus.verify())

    def test_duplicate_delivery_is_claimed_once_and_transient_jobs_dead_letter(self):
        queue = JobQueue(self.redis)
        job = queue.enqueue("test.transient", "APP-RETRY", "APP-RETRY", "DEP-RETRY", {"maxAttempts": 2})
        class TransientError(RuntimeError):
            category = "TIMEOUT"
            retryable = True
        handler = lambda current: (_ for _ in ()).throw(TransientError("upstream timeout"))
        first = run_once(queue, {"test.transient": handler})
        self.assertEqual(first["status"], "QUEUED")
        second = run_once(queue, {"test.transient": handler})
        self.assertEqual(second["status"], "DEAD_LETTER")
        self.assertEqual(second["error"]["category"], "TIMEOUT")
        self.memory.rpush(queue.queue_name, json.dumps(job))
        duplicate = run_once(queue, {"test.transient": handler})
        self.assertEqual(duplicate["status"], "DUPLICATE_OR_ALREADY_FINISHED")

    def test_revoked_consent_cancels_queued_provider_job_without_adapter_call(self):
        citizen_id = "CITIZEN_001"
        receipt = create_consent(citizen_id, True)
        persist_state()
        result = discover(CITIZENS[citizen_id])
        app = create_application(citizen_id, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        dependency = ensure_domicile_dependency(app)
        queued = initiate_domicile(citizen_id, app)
        revoke_consent(citizen_id, receipt["consentId"])
        persist_state()
        with patch("app.engine.dependency_orchestrator.request_registered_service") as adapter:
            finished = run_once(JobQueue(self.redis), {})
        self.assertEqual(finished["status"], "FAILED")
        self.assertEqual(finished["error"]["category"], "AUTHORIZATION_ERROR")
        self.assertEqual(dependency["jobStatus"], "CANCELLED")
        adapter.assert_not_called()
        self.assertTrue(any(event["type"] == "PROVIDER_JOB_CANCELLED" for event in event_bus.events))

    def test_revocation_is_visible_after_fresh_hydration(self):
        citizen_id = "CITIZEN_001"
        receipt = create_consent(citizen_id, True)
        revoke_consent(citizen_id, receipt["consentId"])
        from app.engine import consent_manager
        consent_manager.CONSENTS.clear()
        from app.core.persistence import hydrate_state
        hydrate_state()
        with self.assertRaises(ConsentAuthorizationError):
            authorize_persisted_access(citizen_id, CONSUMER, PURPOSE, consent_id=receipt["consentId"])

    def test_concurrent_revoke_waits_for_locked_provider_execution(self):
        citizen_id = "CITIZEN_001"
        receipt = create_consent(citizen_id, True)
        started = threading.Event()
        release = threading.Event()
        revoked = threading.Event()
        calls = []

        def provider_call():
            calls.append("called")
            started.set()
            release.wait(timeout=5)
            return "provider-result"

        result = {}
        def execute():
            result["value"] = execute_with_persisted_authorization(
                citizen_id, CONSUMER, PURPOSE, consent_id=receipt["consentId"], operation=provider_call
            )

        executor = threading.Thread(target=execute)
        executor.start()
        self.assertTrue(started.wait(timeout=5))
        revoker = threading.Thread(target=lambda: (revoke_consent(citizen_id, receipt["consentId"]), revoked.set()))
        revoker.start()
        time.sleep(0.2)
        self.assertFalse(revoked.is_set())
        release.set()
        executor.join(timeout=5)
        revoker.join(timeout=5)
        self.assertEqual(result["value"], "provider-result")
        self.assertTrue(revoked.is_set())
        self.assertEqual(calls, ["called"])


if __name__ == "__main__":
    unittest.main()
