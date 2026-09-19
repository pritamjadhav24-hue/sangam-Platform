"""Optional single-process worker entry point for Redis-backed jobs."""
from __future__ import annotations

import time

from app.core.job_queue import JobQueue, safe_error_message
from app.core.redis_service import RedisService


def run_once(queue: JobQueue, handlers: dict):
    job = queue.dequeue()
    if not job: return None
    claimed = queue.claim(job)
    if not claimed:
        return {**job, "status": "DUPLICATE_OR_ALREADY_FINISHED"}
    job = claimed
    handler = handlers.get(job["jobType"])
    if handler is None and job["jobType"] == "provider.dependency.retrieve":
        from app.engine.dependency_orchestrator import execute_provider_job
        handler = execute_provider_job
    if not handler:
        job["status"] = "FAILED"; job["error"] = {"category": "UNKNOWN_JOB"}
        job["completedAt"] = __import__("app.core.job_queue", fromlist=["now"]).now()
        queue.update(job)
        return job
    try:
        handler(job)
        job["status"] = "COMPLETED"
    except Exception as error:
        category = getattr(error, "category", "WORKER_ERROR")
        retryable = getattr(error, "retryable", category in {"TRANSIENT", "TIMEOUT", "UPSTREAM_UNAVAILABLE"})
        if retryable and job["attempt"] < job["maxAttempts"]:
            job["status"] = "QUEUED"; job["error"] = {"category": category, "message": safe_error_message(error)}
            queue.update(job)
            queue.redis.enqueue(queue.queue_name, job)
            from app.core.event_bus import event_bus
            event_bus.publish("PROVIDER_JOB_RETRYING", {"appId": job.get("applicationId"), "dependencyId": job.get("dependencyId"), "jobId": job["jobId"], "correlationId": job["correlationId"], "attempt": job["attempt"], "maxAttempts": job["maxAttempts"], "errorCategory": category})
            return job
        job["status"] = "DEAD_LETTER" if retryable else "FAILED"
        job["error"] = {"category": category, "message": safe_error_message(error)}
        if job["jobType"] == "provider.dependency.retrieve":
            from app.engine.dependency_orchestrator import mark_provider_job_dead_letter
            mark_provider_job_dead_letter(job, category, str(error))
    job["completedAt"] = __import__("app.core.job_queue", fromlist=["now"]).now()
    queue.update(job)
    return job


def main():
    from app.core.persistence import initialize, hydrate_state
    initialize()
    hydrate_state()
    service = RedisService(enabled=True)
    queue = JobQueue(service)
    queue.recover()
    while True:
        service.set("sangam:worker:heartbeat", "alive", 15)
        run_once(queue, {})
        time.sleep(0.25)


if __name__ == "__main__": main()
