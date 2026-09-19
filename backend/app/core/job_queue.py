"""Small generic job abstraction; Redis is coordination/transport, not state."""
from __future__ import annotations

import uuid
import re
from datetime import datetime, timezone

from app.core.redis_service import RedisService, RedisUnavailable


def now(): return datetime.now(timezone.utc).isoformat()


def _safe_payload(payload: dict) -> dict:
    blocked = ("citizen", "password", "secret", "token", "jwt", "authorization", "credential", "document", "address", "phone", "email", "dob")
    if not isinstance(payload, dict):
        raise ValueError("Job payload must be an object")
    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if any(term in str(key).lower() for term in blocked):
                    raise ValueError("Job payload contains a prohibited sensitive field")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(payload)
    return payload


def safe_error_message(message: str) -> str:
    value = str(message or "")
    value = re.sub(r"(?i)(password|secret|token|authorization|client_secret)\s*[=:]\s*[^,;\s]+", r"\1=[REDACTED]", value)
    return value[:500]


class JobQueue:
    def __init__(self, redis: RedisService, queue_name="sangam:jobs"):
        if not redis.enabled:
            raise RedisUnavailable("Job queues require REDIS_ENABLED=true")
        self.redis, self.queue_name = redis, queue_name

    def enqueue(self, job_type, correlation_id, application_id=None, dependency_id=None, payload=None):
        payload = _safe_payload(payload or {})
        max_attempts = int(payload.get("maxAttempts", 3))
        if not 1 <= max_attempts <= 10:
            raise ValueError("maxAttempts must be between 1 and 10")
        job = {"jobId": f"JOB-{uuid.uuid4().hex}", "jobType": job_type, "correlationId": correlation_id, "applicationId": application_id, "dependencyId": dependency_id, "providerId": payload.get("providerId"), "attempt": 0, "maxAttempts": max_attempts, "status": "QUEUED", "createdAt": now(), "startedAt": None, "completedAt": None, "error": None, "payload": payload}
        from app.core.persistence import persist_provider_job
        persist_provider_job(job)
        self.redis.enqueue(self.queue_name, job)
        return job

    def dequeue(self):
        return self.redis.dequeue(self.queue_name)

    def claim(self, job):
        from app.core.persistence import claim_provider_job
        return claim_provider_job(job["jobId"])

    def update(self, job):
        from app.core.persistence import update_provider_job
        return update_provider_job(job)

    def recover(self):
        jobs = []
        from app.core.persistence import recover_provider_jobs
        for job in recover_provider_jobs():
            self.redis.enqueue(self.queue_name, job)
            jobs.append(job)
        return jobs
