import time
import unittest

from app.core.job_queue import JobQueue
from app.core.redis_service import MemoryRedis, RedisConfigurationError, RedisService, RedisUnavailable, build_test_redis_service
from app.worker import run_once


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
        recovered = queue.recover()
        self.assertEqual([item["jobId"] for item in recovered], [job["jobId"]])
        result = run_once(queue, {"restart.test": lambda current: None})
        self.assertEqual(result["status"], "COMPLETED")

    def test_job_payload_rejects_sensitive_identity_fields(self):
        redis = build_test_redis_service(MemoryRedis())
        with self.assertRaises(ValueError):
            JobQueue(redis).enqueue("unsafe", "APP-1", payload={"citizenId": "CITIZEN_001"})


if __name__ == "__main__":
    unittest.main()
