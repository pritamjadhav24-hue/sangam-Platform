import os
import json
import unittest
from unittest.mock import patch

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.event_bus import event_bus
from app.core.notification_manager import notification_manager
from app.core.persistence import persist_state
from app.core.redis_service import MemoryRedis, build_test_redis_service
from app.engine.adapters import set_integration_availability
from app.engine.consent_manager import create_consent
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
        create_consent(citizen_id, True)
        result = discover(CITIZENS[citizen_id])
        app = create_application(citizen_id, result, evaluate(result["requirements"]))
        dependency = ensure_domicile_dependency(app)
        queued = initiate_domicile(citizen_id, app)
        self.assertTrue(queued["queued"])
        self.assertEqual(dependency["jobStatus"], "QUEUED")
        self.assertNotIn("citizenId", json.loads(self.memory.lists["sangam:jobs"][0])["payload"])
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


if __name__ == "__main__":
    unittest.main()
