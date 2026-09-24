import unittest
from fastapi import HTTPException

from app.api.admin_routes import router
from app.core.auth import require_roles
from app.core.observability import structured_log
from app.core.persistence import job_operational_summary, record_worker_heartbeat, worker_operational_status
from app.core.persistence import provider_job_detail, replay_dead_letter_job
from app.core.job_queue import JobQueue
from app.core.redis_service import MemoryRedis, RedisService, build_test_redis_service
from app.core.persistence import ProviderJobRow, Session, WorkerHeartbeatRow, engine


def _delete_rows(model, column, value):
    with Session(engine) as session:
        session.query(model).filter(column == value).delete(synchronize_session=False)
        session.commit()


class ObservabilityTests(unittest.TestCase):
    def test_structured_log_is_allowlisted_and_correlation_safe(self):
        record = structured_log("test_operation", correlation_id="APP-OBS", application_id="APP-OBS", token="do-not-log", raw_response={"citizenId": "CITIZEN_001"})
        self.assertEqual(record["correlation_id"], "APP-OBS")
        self.assertNotIn("token", record)
        self.assertNotIn("raw_response", record)

    def test_worker_heartbeat_and_postgres_job_metrics_are_operational_views(self):
        self.addCleanup(_delete_rows, WorkerHeartbeatRow, WorkerHeartbeatRow.worker_id, "test-worker")
        record_worker_heartbeat("test-worker", "AVAILABLE", build_test_redis_service(MemoryRedis()).health_check()["status"])
        self.assertTrue(any(item["workerId"] == "test-worker" for item in worker_operational_status()))
        summary = job_operational_summary()
        self.assertIn("QUEUED", summary["counts"])
        self.assertIn("DEAD_LETTER", summary["counts"])

    def test_operational_routes_and_role_guard_are_admin_only(self):
        paths = {route.path for route in router.routes if "/operations/" in route.path}
        self.assertTrue({"/api/admin/operations/providers", "/api/admin/operations/jobs/summary", "/api/admin/operations/jobs/{job_id}/replay"}.issubset(paths))
        guard = require_roles("ADMIN")
        with self.assertRaises(HTTPException) as error:
            guard({"userId": "CITIZEN_001", "role": "CITIZEN"})
        self.assertEqual(error.exception.status_code, 403)

    def test_dead_letter_replay_requeues_and_redis_failure_does_not_change_state(self):
        redis = build_test_redis_service(MemoryRedis())
        queue = JobQueue(redis)
        job = queue.enqueue("replay.test", "APP-REPLAY", "APP-REPLAY", "DEP-REPLAY", {})
        self.addCleanup(_delete_rows, ProviderJobRow, ProviderJobRow.job_id, job["jobId"])
        claimed = queue.claim(job)
        claimed.update({"status": "DEAD_LETTER", "error": {"category": "TIMEOUT", "message": "safe"}})
        queue.update(claimed)
        replayed = replay_dead_letter_job(job["jobId"], redis)
        self.assertEqual(replayed["status"], "QUEUED")
        self.assertEqual(provider_job_detail(job["jobId"])["status"], "QUEUED")
        claimed = queue.claim(job)
        claimed.update({"status": "DEAD_LETTER", "error": {"category": "TIMEOUT", "message": "safe"}})
        queue.update(claimed)
        with self.assertRaises(RuntimeError):
            replay_dead_letter_job(job["jobId"], RedisService(enabled=False))
        self.assertEqual(provider_job_detail(job["jobId"])["status"], "DEAD_LETTER")


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
