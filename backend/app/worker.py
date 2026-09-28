"""Optional single-process worker entry point for Redis-backed jobs."""
from __future__ import annotations

import time
import os
import socket
import sys
import threading

from app.core.job_queue import JobQueue, safe_error_message
from app.core.redis_service import RedisService
from app.core.observability import structured_log


def worker_id() -> str:
    return os.getenv("SANGAM_WORKER_ID") or f"worker-{socket.gethostname()}-{os.getpid()}"


def record_heartbeat(service: RedisService, identifier: str, status: str = "AVAILABLE", current_job_id: str | None = None) -> None:
    from app.core.persistence import record_worker_heartbeat, renew_provider_job_lease
    redis_status = service.health_check()["status"]
    if status == "BUSY" and current_job_id:
        renew_provider_job_lease(current_job_id, identifier)
    record_worker_heartbeat(identifier, status, redis_status, current_job_id)


def run_once(queue: JobQueue, handlers: dict, worker_id: str | None = None):
    job = queue.dequeue()
    if not job: return None
    claimed = queue.claim(job, worker_id=worker_id)
    if not claimed:
        return {**job, "status": "DUPLICATE_OR_ALREADY_FINISHED"}
    job = claimed
    operation_started = time.perf_counter()
    if worker_id:
        record_heartbeat(queue.redis, worker_id, "BUSY", job["jobId"])
    structured_log("provider_job_claimed", correlation_id=job["correlationId"], application_id=job.get("applicationId"), dependency_id=job.get("dependencyId"), job_id=job["jobId"], provider_id=job.get("providerId"), attempt=job["attempt"], max_attempts=job["maxAttempts"], status="RUNNING")
    handler = handlers.get(job["jobType"])
    if handler is None and job["jobType"] == "provider.dependency.retrieve":
        from app.engine.dependency_orchestrator import execute_provider_job
        handler = execute_provider_job
    if not handler:
        job["status"] = "FAILED"; job["error"] = {"category": "UNKNOWN_JOB"}
        job["completedAt"] = __import__("app.core.job_queue", fromlist=["now"]).now()
        if queue.update(job) is None:
            return {**job, "status": "STALE_LEASE"}
        if worker_id: record_heartbeat(queue.redis, worker_id)
        structured_log("provider_job_failed", level="ERROR", correlation_id=job["correlationId"], application_id=job.get("applicationId"), dependency_id=job.get("dependencyId"), job_id=job["jobId"], provider_id=job.get("providerId"), outcome="FAILED", error_category="UNKNOWN_JOB")
        return job
    lease_stop = threading.Event()
    lease_thread = None
    if worker_id:
        from app.core.persistence import renew_provider_job_lease
        def renew_lease_loop():
            while not lease_stop.wait(10):
                if not renew_provider_job_lease(job["jobId"], worker_id):
                    break
        lease_thread = threading.Thread(target=renew_lease_loop, name=f"lease-{job['jobId']}", daemon=True)
        lease_thread.start()

    def stop_lease_renewal():
        lease_stop.set()
        if lease_thread:
            lease_thread.join(timeout=1)

    try:
        handler(job)
        job["status"] = "COMPLETED"
    except Exception as error:
        category = getattr(error, "category", "WORKER_ERROR")
        retryable = getattr(error, "retryable", category in {"TRANSIENT", "TIMEOUT", "UPSTREAM_UNAVAILABLE"})
        if retryable and job["attempt"] < job["maxAttempts"]:
            job["status"] = "QUEUED"; job["error"] = {"category": category, "message": safe_error_message(error)}
            if queue.update(job) is None:
                stop_lease_renewal()
                return {**job, "status": "STALE_LEASE"}
            if job["jobType"] == "provider.dependency.retrieve":
                from app.core.persistence import persist_state
                persist_state()
            queue.redis.enqueue(queue.queue_name, job)
            from app.core.persistence import mark_provider_job_dispatched
            mark_provider_job_dispatched(job["jobId"])
            from app.core.event_bus import event_bus
            event_bus.publish("PROVIDER_JOB_RETRYING", {"appId": job.get("applicationId"), "dependencyId": job.get("dependencyId"), "jobId": job["jobId"], "correlationId": job["correlationId"], "attempt": job["attempt"], "maxAttempts": job["maxAttempts"], "errorCategory": category})
            structured_log("provider_job_retrying", level="WARNING", correlation_id=job["correlationId"], application_id=job.get("applicationId"), dependency_id=job.get("dependencyId"), job_id=job["jobId"], provider_id=job.get("providerId"), attempt=job["attempt"], max_attempts=job["maxAttempts"], duration_ms=round((time.perf_counter() - operation_started) * 1000, 2), outcome="QUEUED", error_category=category)
            stop_lease_renewal()
            if worker_id: record_heartbeat(queue.redis, worker_id)
            return job
        job["status"] = "DEAD_LETTER" if retryable else "FAILED"
        job["error"] = {"category": category, "message": safe_error_message(error)}
    job["completedAt"] = __import__("app.core.job_queue", fromlist=["now"]).now()
    if queue.update(job) is None:
        stop_lease_renewal()
        return {**job, "status": "STALE_LEASE"}
    stop_lease_renewal()
    if job["jobType"] == "provider.dependency.retrieve" and job["status"] != "COMPLETED":
        from app.engine.dependency_orchestrator import mark_provider_job_cancelled, mark_provider_job_dead_letter
        if (job.get("error") or {}).get("category") == "AUTHORIZATION_ERROR":
            mark_provider_job_cancelled(job, (job.get("error") or {}).get("category"), (job.get("error") or {}).get("message", ""))
        else:
            mark_provider_job_dead_letter(job, (job.get("error") or {}).get("category"), (job.get("error") or {}).get("message", ""))
    if job["jobType"] == "provider.dependency.retrieve":
        from app.core.persistence import persist_state
        persist_state()
    if worker_id: record_heartbeat(queue.redis, worker_id)
    structured_log("provider_job_finished", level="ERROR" if job["status"] != "COMPLETED" else "INFO", correlation_id=job["correlationId"], application_id=job.get("applicationId"), dependency_id=job.get("dependencyId"), job_id=job["jobId"], provider_id=job.get("providerId"), attempt=job["attempt"], max_attempts=job["maxAttempts"], duration_ms=round((time.perf_counter() - operation_started) * 1000, 2), status=job["status"], outcome="SUCCESS" if job["status"] == "COMPLETED" else "FAILED", error_category=(job.get("error") or {}).get("category"))
    return job


def main():
    from app.core.persistence import initialize, hydrate_state
    from main import load_integration_env  # same department endpoints as the API process
    load_integration_env()
    initialize()
    hydrate_state()
    service = RedisService(enabled=True)
    queue = JobQueue(service)
    identifier = worker_id()
    queue.recover()
    queue.reconcile(limit=int(os.getenv("PROVIDER_JOB_RECONCILE_BATCH", "25")), lease_seconds=int(os.getenv("PROVIDER_JOB_RECONCILE_LEASE_SECONDS", "30")))
    record_heartbeat(service, identifier)
    structured_log("worker_started", worker_id=identifier, worker_status="AVAILABLE", queue=queue.queue_name)
    last_heartbeat = 0.0
    last_reconciliation = 0.0
    reconciliation_interval = max(5, min(int(os.getenv("PROVIDER_JOB_RECONCILE_INTERVAL_SECONDS", "15")), 300))
    while True:
        now = time.monotonic()
        if now - last_heartbeat >= 5:
            service.set("sangam:worker:heartbeat", "alive", 15)
            record_heartbeat(service, identifier)
            last_heartbeat = now
        if now - last_reconciliation >= reconciliation_interval:
            try:
                queue.reconcile(limit=int(os.getenv("PROVIDER_JOB_RECONCILE_BATCH", "25")), lease_seconds=int(os.getenv("PROVIDER_JOB_RECONCILE_LEASE_SECONDS", "30")))
            except Exception as error:
                structured_log("provider_job_reconciliation_failed", level="WARNING", error_category=type(error).__name__)
            last_reconciliation = now
        run_once(queue, {}, worker_id=identifier)
        time.sleep(0.25)


def healthcheck() -> int:
    """Container healthcheck: infrastructure and a fresh worker heartbeat are required."""
    from app.core.persistence import initialize, worker_operational_status
    initialize()
    service = RedisService(enabled=True)
    service.health_check()
    heartbeat = service.get("sangam:worker:heartbeat")
    workers = worker_operational_status()
    if not heartbeat or not any(item["status"] == "AVAILABLE" and item["redisStatus"] == "AVAILABLE" for item in workers):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(healthcheck() if "--healthcheck" in sys.argv else (main() or 0))
