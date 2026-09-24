import time
import unittest
import uuid
from unittest.mock import patch

from app.core.job_queue import JobQueue
from app.core.redis_service import MemoryRedis, RedisConfigurationError, RedisService, RedisUnavailable, build_test_redis_service
from app.worker import run_once
from app.core.persistence import ProviderJobRow, engine, recover_provider_jobs
from sqlalchemy.orm import Session


class RedisJobTests(unittest.TestCase):
    def test_cache_ttl_and_invalidation(self):
        memory = MemoryRedis()
        redis = build_test_redis_service(memory)
        redis.set_json("catalog", {"schemes": ["safe-metadata"]}, 1)
        self.assertEqual(redis.get_json("catalog")["schemes"], ["safe-metadata"])
        time.sleep(1.05)
        self.assertIsNone(redis.get_json("catalog"))
        redis.set("catalog", "value", 30)
        redis.delete("catalog")
        self.assertIsNone(redis.get("catalog"))

    def test_queue_worker_metadata_and_idempotent_payload(self):
        redis = build_test_redis_service(MemoryRedis())
        queue = JobQueue(redis)
        job = queue.enqueue("provider.retrieve", "APP-1", "APP-1", "DEP-1", {"safe": True})
        handled = []
        result = run_once(queue, {"provider.retrieve": lambda current: handled.append(current["jobId"])})
        self.assertEqual(result["jobId"], job["jobId"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(handled, [job["jobId"]])
        self.assertEqual(result["correlationId"], "APP-1")
        self.assertEqual(result["dependencyId"], "DEP-1")

    def test_invalid_enabled_configuration_fails_clearly(self):
        with self.assertRaises(RedisConfigurationError):
            RedisService(enabled=True, url="http://not-redis")

    def test_queue_cannot_silently_use_disabled_redis(self):
        with self.assertRaises(RedisUnavailable):
            JobQueue(RedisService(enabled=False))

    def test_short_lived_lock_is_available_at_service_boundary(self):
        redis = build_test_redis_service(MemoryRedis())
        with redis.lock("application:APP-1"):
            self.assertEqual(redis.get("lock:application:APP-1"), "1")
        self.assertIsNone(redis.get("lock:application:APP-1"))

    def test_restart_requeues_abandoned_running_job_from_postgres(self):
        redis = build_test_redis_service(MemoryRedis())
        queue = JobQueue(redis)
        job = queue.enqueue("restart.test", "APP-RESTART", "APP-RESTART", "DEP-RESTART", {})
        self.assertIsNotNone(queue.claim(job))
        from datetime import datetime, timedelta, timezone
        with Session(engine) as session:
            row = session.get(ProviderJobRow, job["jobId"])
            row.lease_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            session.commit()
        recovered = queue.recover()
        self.assertEqual([item["jobId"] for item in recovered], [job["jobId"]])
        result = run_once(queue, {"restart.test": lambda current: None})
        self.assertEqual(result["status"], "COMPLETED")

    def test_job_payload_rejects_sensitive_identity_fields(self):
        redis = build_test_redis_service(MemoryRedis())
        with self.assertRaises(ValueError):
            JobQueue(redis).enqueue("unsafe", "APP-1", payload={"citizenId": "CITIZEN_001"})

    def test_queued_job_reconciles_after_initial_redis_failure_and_is_not_republished_twice(self):
        with Session(engine) as session:
            session.query(ProviderJobRow).filter((ProviderJobRow.application_id == "APP-RECONCILE") | ProviderJobRow.application_id.like("APP-RECONCILE-%")).delete(synchronize_session=False)
            session.commit()
        app_id = f"APP-RECONCILE-{uuid.uuid4().hex}"
        with Session(engine) as session:
            session.query(ProviderJobRow).filter(ProviderJobRow.status == "QUEUED").delete(synchronize_session=False)
            session.commit()
        class FailingRedis:
            enabled = True
            def enqueue(self, *_args):
                raise RedisUnavailable("temporary redis outage")
        with self.assertRaises(RedisUnavailable):
            JobQueue(FailingRedis()).enqueue("reconcile.test", app_id, app_id, f"DEP-{app_id}", {})
        with Session(engine) as session:
            row = session.query(ProviderJobRow).filter_by(application_id=app_id).one()
            self.assertEqual(row.status, "QUEUED")
        memory = MemoryRedis()
        redis = build_test_redis_service(memory)
        queue = JobQueue(redis)
        self.assertEqual(queue.reconcile(limit=1)["dispatched"], 1)
        self.assertEqual(queue.reconcile(limit=1)["eligible"], 0)
        self.assertEqual(len(memory.lists[queue.queue_name]), 1)

    def test_live_worker_lease_is_not_recovered_but_expired_lease_is(self):
        redis = build_test_redis_service(MemoryRedis())
        queue = JobQueue(redis)
        with Session(engine) as session:
            session.query(ProviderJobRow).delete(synchronize_session=False)
            session.commit()
        job = queue.enqueue("lease.test", "APP-LEASE", "APP-LEASE", "DEP-LEASE", {})
        self.assertIsNotNone(queue.claim(job, worker_id="worker-a"))
        self.assertEqual(recover_provider_jobs(), [])
        from datetime import datetime, timedelta, timezone
        with Session(engine) as session:
            row = session.get(ProviderJobRow, job["jobId"])
            row.lease_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            session.commit()
        self.assertEqual([item["jobId"] for item in recover_provider_jobs()], [job["jobId"]])

    def test_stale_worker_results_cannot_overwrite_reclaimed_job(self):
        redis = build_test_redis_service(MemoryRedis())
        queue = JobQueue(redis)
        job = queue.enqueue("stale.test", "APP-STALE", "APP-STALE", "DEP-STALE", {})
        first = queue.claim(job, worker_id="worker-a")
        from datetime import datetime, timedelta, timezone
        with Session(engine) as session:
            row = session.get(ProviderJobRow, job["jobId"])
            row.lease_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            session.commit()
        recover_provider_jobs()
        second = queue.claim(job, worker_id="worker-b")
        self.assertEqual(second["attempt"], first["attempt"] + 1)
        for stale_status in ("COMPLETED", "FAILED", "DEAD_LETTER", "QUEUED"):
            stale = {**first, "status": stale_status, "completedAt": datetime.now(timezone.utc).isoformat()}
            self.assertIsNone(queue.update(stale))
        with Session(engine) as session:
            row = session.get(ProviderJobRow, job["jobId"])
            self.assertEqual(row.status, "RUNNING")
            self.assertEqual(row.lease_owner, "worker-b")
            self.assertEqual(row.attempt, second["attempt"])

    def test_dispatch_lease_expiry_reconciles_lost_redis_message(self):
        memory = MemoryRedis()
        queue = JobQueue(build_test_redis_service(memory))
        job = queue.enqueue("lost.test", "APP-LOST", "APP-LOST", "DEP-LOST", {})
        with Session(engine) as session:
            session.query(ProviderJobRow).filter(ProviderJobRow.status == "QUEUED", ProviderJobRow.job_id != job["jobId"]).delete(synchronize_session=False)
            session.commit()
        memory.lpop(queue.queue_name)
        from datetime import datetime, timedelta, timezone
        with Session(engine) as session:
            row = session.get(ProviderJobRow, job["jobId"])
            row.dispatch_claimed_until = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            session.commit()
        self.assertEqual(queue.reconcile()["dispatched"], 1)
        self.assertEqual(len(memory.lists[queue.queue_name]), 1)


# Some tests here clear the whole provider_jobs table to make recovery
# assertions deterministic; put any pre-existing jobs back afterwards.
from tests.catalog_fixture import restore_tables, snapshot_tables  # noqa: E402
_JOB_SNAPSHOT: list = []


def setUpModule():
    _JOB_SNAPSHOT[:] = snapshot_tables(ProviderJobRow)


def tearDownModule():
    restore_tables(_JOB_SNAPSHOT)

# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
