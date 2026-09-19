"""Small PostgreSQL-backed persistence boundary for the existing in-memory engine.

The domain modules keep their current dictionaries as the runtime cache and API
shape. This module hydrates that cache at startup and snapshots it after each
request, so the prototype can gain restart durability without an architecture
rewrite. PostgreSQL is mandatory; there is deliberately no in-memory fallback.
"""
from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def _load_local_env() -> None:
    if os.getenv("DATABASE_URL"):
        return
    for path in (Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[3] / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return


_load_local_env()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required; PostgreSQL persistence cannot start without it.")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError("DATABASE_URL must use PostgreSQL (postgresql:// or postgresql+psycopg://).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
MIGRATION_HEAD = "0006_provider_contract_metadata"


class Base(DeclarativeBase):
    pass


class ApplicationRow(Base):
    __tablename__ = "applications"
    app_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class DependencyRow(Base):
    __tablename__ = "dependencies"
    dependency_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.app_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class ConsentRow(Base):
    __tablename__ = "consents"
    consent_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(120), index=True)
    app_id: Mapped[Optional[str]] = mapped_column(ForeignKey("applications.app_id", ondelete="SET NULL"), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class EntityReviewRow(Base):
    __tablename__ = "entity_reviews"
    review_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.app_id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class ConflictReviewRow(Base):
    __tablename__ = "conflict_reviews"
    review_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.app_id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class NotificationRow(Base):
    __tablename__ = "notifications"
    notification_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    recipient_user_id: Mapped[str] = mapped_column(String(120), index=True)
    app_id: Mapped[Optional[str]] = mapped_column(ForeignKey("applications.app_id", ondelete="SET NULL"), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class WorkflowHistoryRow(Base):
    __tablename__ = "workflow_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.app_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(50))
    occurred_at: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)


class AuditEntryRow(Base):
    __tablename__ = "audit_entries"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    consent_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class SessionRow(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class UserAccountRow(Base):
    __tablename__ = "user_accounts"
    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONB)


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    occurred_at: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)


class IntegrationStateRow(Base):
    __tablename__ = "integration_state"
    system: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class MockStateRow(Base):
    __tablename__ = "mock_department_state"
    state_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class CounterRow(Base):
    __tablename__ = "counters"
    counter_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer)


class ProviderJobRow(Base):
    __tablename__ = "provider_jobs"
    job_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    application_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    dependency_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    provider_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(40))
    last_seen: Mapped[str] = mapped_column(String(64), index=True)
    current_job_id: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    redis_status: Mapped[str] = mapped_column(String(40))
    postgres_status: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)


class DepartmentRow(Base):
    __tablename__ = "departments"
    department_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class ProviderRow(Base):
    __tablename__ = "providers"
    provider_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id"), index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    adapter_type: Mapped[str] = mapped_column(String(120))
    contract_version: Mapped[str] = mapped_column(String(40), default="v1")
    environment: Mapped[str] = mapped_column(String(20), default="SANDBOX")
    auth_type: Mapped[str] = mapped_column(String(40), default="NONE")
    endpoint_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class ServiceCatalogRow(Base):
    __tablename__ = "service_catalog"
    service_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    requirement_code: Mapped[str] = mapped_column(String(120), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class ProviderCapabilityRow(Base):
    __tablename__ = "provider_capabilities"
    capability_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id", ondelete="CASCADE"), index=True)
    capability_code: Mapped[str] = mapped_column(String(120), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("service_catalog.service_id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class SchemeCatalogRow(Base):
    __tablename__ = "scheme_catalog"
    scheme_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    department: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class SchemeRequirementRow(Base):
    __tablename__ = "scheme_requirements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_id: Mapped[str] = mapped_column(ForeignKey("scheme_catalog.scheme_id", ondelete="CASCADE"), index=True)
    requirement_code: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(200))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSONB)


def initialize() -> None:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
        if version != MIGRATION_HEAD:
            raise RuntimeError(f"Database schema is at migration {version!r}; run 'alembic upgrade head' before starting SANGAM.")
    except Exception as error:
            raise RuntimeError(f"PostgreSQL initialization failed: {error}") from error


def _job_from_row(row: ProviderJobRow) -> dict:
    return {"jobId": row.job_id, "jobType": row.job_type, "status": row.status,
            "correlationId": row.correlation_id, "applicationId": row.application_id,
            "dependencyId": row.dependency_id, "providerId": row.provider_id,
            "attempt": row.attempt, "maxAttempts": row.max_attempts,
            "createdAt": row.created_at, "startedAt": row.started_at,
            "completedAt": row.completed_at, "error": ({"category": row.error_category, "message": row.error_message} if row.error_category else None),
            "payload": row.payload or {}}


def persist_provider_job(job: dict) -> dict:
    """Persist the authoritative job record before it is put on Redis."""
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job["jobId"])
        error = job.get("error") or {}
        from app.core.job_queue import safe_error_message
        values = {"job_type": job["jobType"], "status": job["status"], "correlation_id": job["correlationId"],
                  "application_id": job.get("applicationId"), "dependency_id": job.get("dependencyId"),
                  "provider_id": job.get("providerId"), "attempt": job.get("attempt", 0),
                  "max_attempts": job.get("maxAttempts", 3), "created_at": job["createdAt"],
                  "started_at": job.get("startedAt"), "completed_at": job.get("completedAt"),
                  "error_category": error.get("category"), "error_message": safe_error_message(error.get("message", "")) or None,
                  "payload": job.get("payload") or {}}
        if row is None:
            session.add(ProviderJobRow(job_id=job["jobId"], **values))
        else:
            for key, value in values.items(): setattr(row, key, value)
        session.commit()
    return job


def claim_provider_job(job_id: str) -> dict | None:
    """Atomically claim only a queued job; duplicate deliveries become no-ops."""
    with Session(engine) as session:
        row = session.execute(select(ProviderJobRow).where(ProviderJobRow.job_id == job_id).with_for_update()).scalar_one_or_none()
        if row is None or row.status != "QUEUED":
            return None
        row.status = "RUNNING"
        row.attempt += 1
        row.started_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _job_from_row(row)


def update_provider_job(job: dict) -> dict:
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job["jobId"])
        if row is None:
            raise KeyError(f"Unknown provider job {job['jobId']}")
        row.status = job["status"]
        row.attempt = job.get("attempt", row.attempt)
        row.started_at = job.get("startedAt")
        row.completed_at = job.get("completedAt")
        error = job.get("error") or {}
        row.error_category = error.get("category")
        from app.core.job_queue import safe_error_message
        row.error_message = safe_error_message(error.get("message", "")) or None
        session.commit()
    return job


def recover_provider_jobs() -> list[dict]:
    """Turn abandoned RUNNING jobs back into queued work after a restart."""
    recovered = []
    with Session(engine) as session:
        rows = session.execute(select(ProviderJobRow).where(ProviderJobRow.status.in_(["QUEUED", "RUNNING"])).with_for_update()).scalars().all()
        for row in rows:
            row.status = "QUEUED"
            row.started_at = None
            recovered.append(_job_from_row(row))
        session.commit()
    return recovered


def record_worker_heartbeat(worker_id: str, status: str, redis_status: str, current_job_id: str | None = None) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    with Session(engine) as session:
        row = session.get(WorkerHeartbeatRow, worker_id)
        values = {"status": status, "last_seen": timestamp, "current_job_id": current_job_id,
                  "redis_status": redis_status, "postgres_status": "AVAILABLE", "payload": {"workerId": worker_id}}
        if row is None:
            session.add(WorkerHeartbeatRow(worker_id=worker_id, **values))
        else:
            for key, value in values.items(): setattr(row, key, value)
        session.commit()
    return {"workerId": worker_id, "status": status, "lastSeen": timestamp, "currentJobId": current_job_id, "redisStatus": redis_status, "postgresStatus": "AVAILABLE"}


def worker_operational_status(stale_after_seconds: int = 15) -> list[dict]:
    from datetime import timedelta
    threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    with Session(engine) as session:
        rows = session.query(WorkerHeartbeatRow).order_by(WorkerHeartbeatRow.last_seen.desc()).all()
        result = []
        for row in rows:
            try:
                last_seen = datetime.fromisoformat(row.last_seen)
                if last_seen.tzinfo is None: last_seen = last_seen.replace(tzinfo=timezone.utc)
                fresh = last_seen >= threshold
            except ValueError:
                fresh = False
            result.append({"workerId": row.worker_id, "status": row.status if fresh else "STALE", "lastSeen": row.last_seen, "currentJobId": row.current_job_id, "redisStatus": row.redis_status, "postgresStatus": row.postgres_status})
        return result


def _safe_job_view(row: ProviderJobRow) -> dict:
    error = {"category": row.error_category, "message": row.error_message} if row.error_category else None
    return {"jobId": row.job_id, "type": row.job_type, "status": row.status, "correlationId": row.correlation_id,
            "applicationId": row.application_id, "dependencyId": row.dependency_id, "providerId": row.provider_id,
            "attempt": row.attempt, "maxAttempts": row.max_attempts, "retryCount": max(row.attempt - 1, 0),
            "createdAt": row.created_at, "startedAt": row.started_at, "completedAt": row.completed_at, "error": error}


def job_operational_summary() -> dict:
    with Session(engine) as session:
        rows = session.query(ProviderJobRow).all()
        counts = {status: sum(1 for row in rows if row.status == status) for status in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "DEAD_LETTER")}
        return {"counts": counts, "retryCount": sum(max(row.attempt - 1, 0) for row in rows), "total": len(rows)}


def recent_provider_jobs(limit: int = 50, dead_letter_only: bool = False) -> list[dict]:
    limit = max(1, min(limit, 100))
    with Session(engine) as session:
        query = session.query(ProviderJobRow).order_by(ProviderJobRow.created_at.desc()).limit(limit)
        if dead_letter_only: query = query.filter(ProviderJobRow.status == "DEAD_LETTER")
        return [_safe_job_view(row) for row in query.all()]


def provider_job_detail(job_id: str) -> dict | None:
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job_id)
        return _safe_job_view(row) if row else None


def provider_operational_summary() -> list[dict]:
    with Session(engine) as session:
        jobs = session.query(ProviderJobRow).all()
        health = {row.system: row.payload for row in session.query(IntegrationStateRow).all()}
        providers = session.query(ProviderRow).all()
        result = []
        for provider in providers:
            related = [row for row in jobs if row.provider_id in {provider.provider_id, provider.name}]
            runtime = health.get(provider.name, {}).get("runtimeHealth", {})
            provider_health = next((item for item in __import__("app.engine.adapters", fromlist=["integration_health"]).integration_health() if item["system"] == provider.name), {"status": "UNKNOWN"})
            safe_health = {key: provider_health.get(key) for key in ("status", "lastCheckedAt", "lastSuccessAt", "lastFailureAt", "errorCategory")}
            result.append({"providerId": provider.provider_id, "name": provider.name, "enabled": provider.active,
                           "adapterType": provider.adapter_type, "contractVersion": provider.contract_version, "environment": provider.environment, "authType": provider.auth_type, "endpointRef": provider.endpoint_ref, "configured": bool(provider.payload),
                           "health": safe_health,
                           "lastSuccessAt": runtime.get("lastSuccessAt"), "lastFailureAt": runtime.get("lastFailureAt"),
                           "errorCategory": runtime.get("errorCategory"),
                           "successCount": sum(1 for row in related if row.status == "COMPLETED"),
                           "failureCount": sum(1 for row in related if row.status in {"FAILED", "DEAD_LETTER"})})
        return result


def replay_dead_letter_job(job_id: str, redis_service) -> dict:
    """Reset and enqueue a dead-letter job, rolling back if Redis cannot accept it."""
    from app.core.observability import structured_log
    from app.core.event_bus import event_bus
    from app.core.audit_bus import audit_bus
    if not redis_service.enabled:
        raise RuntimeError("Redis is required for dead-letter replay")
    redis_service.health_check()
    with Session(engine) as session:
        row = session.execute(select(ProviderJobRow).where(ProviderJobRow.job_id == job_id).with_for_update()).scalar_one_or_none()
        if row is None: raise KeyError(job_id)
        if row.status != "DEAD_LETTER": raise ValueError("Only DEAD_LETTER jobs can be replayed")
        dependency = session.get(DependencyRow, row.dependency_id) if row.dependency_id else None
        if dependency and dependency.payload.get("status") == "COMPLETED": raise ValueError("Dependency is already completed")
        row.status, row.attempt, row.started_at, row.completed_at = "QUEUED", 0, None, None
        row.error_category, row.error_message = None, None
        if dependency:
            dependency.status = "WAITING_FOR_DEPENDENCY"
            dependency.payload = {**dependency.payload, "jobStatus": "QUEUED", "lastError": None, "errorCategory": None}
        replay_payload = {"jobId": row.job_id, "jobType": row.job_type, "correlationId": row.correlation_id, "applicationId": row.application_id, "dependencyId": row.dependency_id, "providerId": row.provider_id, "attempt": 0, "maxAttempts": row.max_attempts, "status": "QUEUED", "createdAt": row.created_at, "startedAt": None, "completedAt": None, "error": None, "payload": row.payload or {}}
        redis_service.enqueue("sangam:jobs", replay_payload)
        replay_result = {"jobId": row.job_id, "type": row.job_type, "status": row.status, "correlationId": row.correlation_id,
                         "applicationId": row.application_id, "dependencyId": row.dependency_id, "providerId": row.provider_id,
                         "attempt": row.attempt, "maxAttempts": row.max_attempts, "retryCount": 0,
                         "createdAt": row.created_at, "startedAt": row.started_at, "completedAt": row.completed_at, "error": None}
        session.commit()
    event = event_bus.publish("PROVIDER_JOB_REPLAYED", {"appId": replay_result["applicationId"], "dependencyId": replay_result["dependencyId"], "jobId": replay_result["jobId"], "correlationId": replay_result["correlationId"]})
    audit_bus.append("SYSTEM", "PROVIDER_JOB", "Administrator replayed dead-letter provider job", replay_result["providerId"] or "CONFIGURED_PROVIDER", "REPLAY", correlation_id=replay_result["correlationId"], payload={"jobId": replay_result["jobId"], "dependencyId": replay_result["dependencyId"], "eventId": event["eventId"]})
    structured_log("provider_job_replayed", correlation_id=replay_result["correlationId"], application_id=replay_result["applicationId"], dependency_id=replay_result["dependencyId"], job_id=replay_result["jobId"], provider_id=replay_result["providerId"], outcome="QUEUED")
    return replay_result


def catalog_seeded() -> bool:
    with Session(engine) as session:
        return session.query(SchemeCatalogRow).count() > 0


def seed_catalog() -> None:
    """Bootstrap catalog rows once; subsequent changes are DB-owned."""
    if os.getenv("SANGAM_SEED_CATALOG", "false").lower() not in {"1", "true", "yes"}:
        return
    from app.engine.registry import DEPENDENCY_SERVICES, SCHEMES
    departments: dict[str, dict] = {}
    with Session(engine) as session:
        for scheme in SCHEMES:
            department = scheme["department"]
            department_id = department.upper().replace(" ", "-")
            departments[department_id] = {"departmentId": department_id, "name": department}
            if session.get(SchemeCatalogRow, scheme["id"]) is None:
                session.add(SchemeCatalogRow(scheme_id=scheme["id"], name=scheme["name"], department=department, payload=scheme))
                for requirement in scheme.get("requirements", []):
                    session.add(SchemeRequirementRow(scheme_id=scheme["id"], requirement_code=requirement["code"], label=requirement["label"], mandatory=requirement.get("mandatory", True), payload=requirement))
        for department_id, department in departments.items():
            if session.get(DepartmentRow, department_id) is None:
                session.add(DepartmentRow(department_id=department_id, name=department["name"], payload=department))
        session.flush()
        for definition in DEPENDENCY_SERVICES:
            provider_id = definition["provider"].upper().replace(" ", "-")
            if session.get(DepartmentRow, provider_id) is None:
                session.add(DepartmentRow(department_id=provider_id, name=definition["provider"], payload={"departmentId": provider_id, "name": definition["provider"]}))
            if session.get(ProviderRow, provider_id) is None:
                session.add(ProviderRow(provider_id=provider_id, department_id=provider_id, name=definition["provider"], adapter_type=definition["adapter"], environment=definition.get("environment", "SANDBOX"), auth_type=definition.get("authType", "NONE"), endpoint_ref=definition.get("endpointRef"), timeout_seconds=definition.get("timeoutSeconds", 5), max_attempts=definition.get("maxAttempts", 3), payload={"providerId": provider_id, "name": definition["provider"], "adapter": definition["adapter"]}))
            if session.get(ServiceCatalogRow, definition["serviceId"]) is None:
                session.add(ServiceCatalogRow(service_id=definition["serviceId"], provider_id=provider_id, name=definition["serviceName"], requirement_code=definition["requirementCode"], payload=definition))
            else:
                existing_service = session.get(ServiceCatalogRow, definition["serviceId"])
                existing_service.payload = {**(existing_service.payload or {}), **definition}
            capability_id = f"{provider_id}:{definition['requirementCode']}"
            if session.get(ProviderCapabilityRow, capability_id) is None:
                session.add(ProviderCapabilityRow(capability_id=capability_id, provider_id=provider_id, capability_code=definition["requirementCode"], service_id=definition["serviceId"], payload={"capabilityId": capability_id, "capabilityCode": definition["requirementCode"], "providerId": provider_id, "serviceId": definition["serviceId"]}))
        session.commit()
    from app.core.redis_service import RedisService
    RedisService().delete("sangam:cache:catalog:v1")


def catalog_snapshot() -> dict:
    from app.core.provider_config import provider_runtime_config
    from app.core.redis_service import RedisService
    cache = RedisService()
    cached = cache.get_json("sangam:cache:catalog:v1")
    if cached:
        return cached
    def safe_payload(payload: dict) -> dict:
        blocked = {"password", "secret", "token", "credential", "clientsecret", "client_secret"}
        return {key: value for key, value in payload.items() if not any(term in key.lower() for term in blocked)}
    with Session(engine) as session:
        schemes = [safe_payload(row.payload) for row in session.query(SchemeCatalogRow).filter_by(active=True).all()]
        services = [safe_payload(row.payload) for row in session.query(ServiceCatalogRow).filter_by(active=True).all()]
        capabilities = [safe_payload(row.payload) for row in session.query(ProviderCapabilityRow).filter_by(enabled=True).all()]
        departments = [safe_payload(row.payload) for row in session.query(DepartmentRow).filter_by(active=True).all()]
        safe_providers = []
        for row in session.query(ProviderRow).filter_by(active=True).all():
            safe_providers.append({"providerId": row.provider_id, "name": row.name, "departmentId": row.department_id, "adapter": row.adapter_type, "contractVersion": row.contract_version, "environment": row.environment, "authType": row.auth_type, "endpointRef": row.endpoint_ref, "timeoutSeconds": row.timeout_seconds, "maxAttempts": row.max_attempts, "runtime": provider_runtime_config(row.provider_id, {**(row.payload or {}), "endpointRef": row.endpoint_ref, "authType": row.auth_type})})
        snapshot = {"schemes": schemes, "services": services, "capabilities": capabilities, "departments": departments, "providers": safe_providers}
        cache.set_json("sangam:cache:catalog:v1", snapshot, 300)
        return snapshot


def citizen_service_snapshot(service_id: str | None = None) -> list[dict] | dict | None:
    """Return the citizen-safe service catalog assembled from normalized DB rows.

    Provider, adapter, endpoint and runtime details intentionally do not cross this
    boundary.  The scheme catalog is the public application-service catalog while
    provider_capabilities remains the internal dependency selection source.
    """
    def requirement_view(row: SchemeRequirementRow) -> dict:
        metadata = row.payload or {}
        return {
            "code": row.requirement_code,
            "label": row.label,
            "mandatory": row.mandatory,
            "requirementType": metadata.get("requirementType", "VERIFICATION"),
            "source": metadata.get("source", "GOVERNMENT_SERVICE"),
            "dependencyServiceId": metadata.get("dependencyServiceId"),
        }

    with Session(engine) as session:
        rows = session.query(SchemeCatalogRow).filter_by(active=True).all()
        result = []
        for row in rows:
            metadata = row.payload or {}
            requirements = [requirement_view(item) for item in session.query(SchemeRequirementRow).filter_by(scheme_id=row.scheme_id).order_by(SchemeRequirementRow.id).all()]
            result.append({
                "serviceId": row.scheme_id,
                "schemeId": row.scheme_id,
                "name": row.name,
                "nameMr": metadata.get("nameMr", row.name),
                "department": row.department,
                "description": metadata.get("description", "Configured government service"),
                "category": metadata.get("category", "Government services"),
                "enabled": row.active,
                "requirements": requirements,
            })
    if service_id is not None:
        return next((item for item in result if item["serviceId"] == service_id), None)
    return result


def ensure_user_accounts() -> None:
    """Migrate existing demo identities into hashed PostgreSQL accounts once."""
    from app.core.auth import hash_password
    from app.mocks.identity_provider import USERS

    if os.getenv("SANGAM_SEED_DEMO_USERS", "false").lower() not in {"1", "true", "yes"}:
        return

    with Session(engine) as session:
        if session.query(UserAccountRow).count():
            return
        password_env = {
            "CITIZEN_001": "SANGAM_CITIZEN_001_PASSWORD",
            "CITIZEN_002": "SANGAM_CITIZEN_002_PASSWORD",
            "OFFICER_MH_01": "SANGAM_OFFICER_MH_01_PASSWORD",
            "ADMIN_MH_01": "SANGAM_ADMIN_MH_01_PASSWORD",
        }
        for user in USERS.values():
            public_user = {key: value for key, value in user.items() if key != "password"}
            password = os.getenv(password_env[user["userId"]])
            if not password:
                raise RuntimeError(f"Missing bootstrap password environment variable for {user['userId']}.")
            session.add(UserAccountRow(
                user_id=user["userId"],
                role=user["role"],
                password_hash=hash_password(password),
                payload=public_user,
            ))
        session.commit()


def _int_suffix(value: str, default: int) -> int:
    try:
        return int(value.rsplit("-", 1)[-1]) + 1
    except (ValueError, AttributeError):
        return default


def persist_state() -> None:
    from app.core.audit_bus import audit_bus
    from app.core.event_bus import event_bus
    from app.core.notification_manager import notification_manager
    from app.engine import adapters, consent_manager, dependency_orchestrator, semantic_mapper, workflow_engine
    from app.mocks import education_dept, revenue_dept
    from app.mocks.identity_provider import SESSIONS

    with Session(engine) as session:
        for model in (WorkflowHistoryRow, EventRow, AuditEntryRow, NotificationRow, EntityReviewRow, ConflictReviewRow, DependencyRow, ConsentRow, ApplicationRow, SessionRow, IntegrationStateRow, MockStateRow, CounterRow):
            session.execute(delete(model))
        for app_id, app in workflow_engine.APPLICATIONS.items():
            session.add(ApplicationRow(app_id=app_id, citizen_id=app["citizenId"], status=app["status"], payload=app))
            for history in app.get("statusHistory", []):
                session.add(WorkflowHistoryRow(app_id=app_id, status=history["status"], occurred_at=history["at"], payload=history))
        for dep_id, dependency in workflow_engine.DEPENDENCIES.items():
            session.add(DependencyRow(dependency_id=dep_id, app_id=dependency["appId"], status=dependency["status"], payload=dependency))
        for citizen_id, receipt in consent_manager.CONSENTS.items():
            app = next((candidate for candidate in workflow_engine.APPLICATIONS.values() if candidate.get("consentId") == receipt.get("consentId")), None) or workflow_engine.find_active_application(citizen_id)
            session.add(ConsentRow(consent_id=receipt["consentId"], citizen_id=citizen_id, app_id=app["appId"] if app else None, payload=receipt))
        for review_id, review in workflow_engine.ENTITY_REVIEWS.items():
            session.add(EntityReviewRow(review_id=review_id, app_id=review["appId"], payload=review))
        for review_id, review in workflow_engine.CONFLICT_REVIEWS.items():
            session.add(ConflictReviewRow(review_id=review_id, app_id=review["appId"], payload=review))
        for item in notification_manager.notifications:
            session.add(NotificationRow(notification_id=item["notificationId"], recipient_user_id=item["recipientUserId"], app_id=item.get("applicationId"), payload=item))
        for event in event_bus.events:
            payload = event.get("payload", {})
            session.add(EventRow(app_id=payload.get("appId"), event_type=event["type"], occurred_at=event["timestamp"], payload=event))
        for entry in audit_bus.entries:
            session.add(AuditEntryRow(sequence=entry["sequence"], correlation_id=entry.get("correlationId"), consent_id=entry.get("consentId"), payload=entry))
        # JWT access tokens are deliberately not persisted.
        for system, state in adapters._availability.items():
            session.add(IntegrationStateRow(system=system, payload={**state, "runtimeHealth": adapters._runtime_health.get(system, {})}))
        session.add(MockStateRow(state_key="revenue_domicile", payload={"record": revenue_dept.DOMICILE_RECORD}))
        session.add(MockStateRow(state_key="education", payload={"familyAnnualIncome": education_dept.EDUCATION_RECORD["familyAnnualIncome"]}))
        session.add(MockStateRow(state_key="semantic_mapping_reviews", payload={"reviews": semantic_mapper.MAPPING_REVIEWS, "counter": semantic_mapper.MAPPING_REVIEW_COUNTER, "evidence": semantic_mapper.SIMULATED_SCHEMA_EVIDENCE}))
        counters = {
            "application": max([_int_suffix(key, 142) for key in workflow_engine.APPLICATIONS] or [142]),
            "dependency": max([_int_suffix(key, 1) for key in workflow_engine.DEPENDENCIES] or [1]),
            "review": max([_int_suffix(key, 1) for key in workflow_engine.ENTITY_REVIEWS] or [1]),
            "conflict": max([_int_suffix(key, 1) for key in workflow_engine.CONFLICT_REVIEWS] or [1]),
            "notification": max([_int_suffix(item["notificationId"], 1) for item in notification_manager.notifications] or [1]),
        }
        for key, value in counters.items(): session.add(CounterRow(counter_key=key, next_value=value))
        session.commit()


def persist_transition(app: dict, history_entry: dict) -> None:
    """Atomically store the current application snapshot and its new history row."""
    with Session(engine) as session:
        row = session.get(ApplicationRow, app["appId"])
        if row is None:
            session.add(ApplicationRow(app_id=app["appId"], citizen_id=app["citizenId"], status=app["status"], payload=app))
        else:
            row.citizen_id = app["citizenId"]
            row.status = app["status"]
            row.payload = app
        session.add(WorkflowHistoryRow(app_id=app["appId"], status=history_entry["status"], occurred_at=history_entry["at"], payload=history_entry))
        session.commit()


def hydrate_state() -> None:
    from app.core.audit_bus import audit_bus
    from app.core.event_bus import event_bus
    from app.core.notification_manager import notification_manager
    from app.engine import adapters, consent_manager, dependency_orchestrator, semantic_mapper, workflow_engine
    from app.mocks import education_dept, revenue_dept
    from app.mocks.identity_provider import SESSIONS

    with Session(engine) as session:
        applications = session.query(ApplicationRow).all()
        workflow_engine.APPLICATIONS.clear(); workflow_engine.DEPENDENCIES.clear(); workflow_engine.ENTITY_REVIEWS.clear(); workflow_engine.CONFLICT_REVIEWS.clear(); consent_manager.CONSENTS.clear(); notification_manager.notifications.clear(); notification_manager._processed_event_ids.clear(); event_bus.reset(); audit_bus.reset(); SESSIONS.clear(); adapters._availability.clear(); adapters._last_health.clear(); adapters._runtime_health.clear()
        for row in applications: workflow_engine.APPLICATIONS[row.app_id] = row.payload
        for row in session.query(DependencyRow).all(): workflow_engine.DEPENDENCIES[row.dependency_id] = row.payload
        for row in session.query(ConsentRow).all(): consent_manager.CONSENTS[row.citizen_id] = row.payload
        for row in session.query(EntityReviewRow).all(): workflow_engine.ENTITY_REVIEWS[row.review_id] = row.payload
        for row in session.query(ConflictReviewRow).all(): workflow_engine.CONFLICT_REVIEWS[row.review_id] = row.payload
        for app in workflow_engine.APPLICATIONS.values():
            app["dependencies"] = [workflow_engine.DEPENDENCIES[dependency_id] for dependency_id in app.get("dependencyIds", []) if dependency_id in workflow_engine.DEPENDENCIES]
            app["entityReviews"] = [workflow_engine.ENTITY_REVIEWS[review["reviewId"]] for review in app.get("entityReviews", []) if review.get("reviewId") in workflow_engine.ENTITY_REVIEWS]
            app["conflictReviews"] = [workflow_engine.CONFLICT_REVIEWS[review["reviewId"]] for review in app.get("conflictReviews", []) if review.get("reviewId") in workflow_engine.CONFLICT_REVIEWS]
        notification_manager.notifications.extend(row.payload for row in session.query(NotificationRow).order_by(NotificationRow.notification_id).all())
        notification_manager._processed_event_ids.update(item.get("sourceEventId") for item in notification_manager.notifications if item.get("sourceEventId"))
        event_bus.hydrate([row.payload for row in session.query(EventRow).order_by(EventRow.id).all()])
        audit_bus.entries.extend(row.payload for row in session.query(AuditEntryRow).order_by(AuditEntryRow.sequence).all())
        SESSIONS.update({row.session_id: row.payload for row in session.query(SessionRow).all()})
        for row in session.query(IntegrationStateRow).all():
            adapters._availability[row.system] = {key: value for key, value in row.payload.items() if key != "runtimeHealth"}
            adapters._runtime_health[row.system] = row.payload.get("runtimeHealth", {})
        for row in session.query(MockStateRow).all():
            if row.state_key == "revenue_domicile": revenue_dept.DOMICILE_RECORD = row.payload.get("record")
            if row.state_key == "education": education_dept.set_income_conflict(row.payload.get("familyAnnualIncome") == "550000")
            if row.state_key == "semantic_mapping_reviews":
                semantic_mapper.MAPPING_REVIEWS.clear(); semantic_mapper.MAPPING_REVIEWS.update(row.payload.get("reviews", {}))
                semantic_mapper.MAPPING_REVIEW_COUNTER = row.payload.get("counter", 1)
                semantic_mapper.SIMULATED_SCHEMA_EVIDENCE = row.payload.get("evidence", semantic_mapper.SIMULATED_SCHEMA_EVIDENCE)
        counters = {row.counter_key: row.next_value for row in session.query(CounterRow).all()}
        workflow_engine._counter = itertools.count(counters.get("application", 142)); dependency_orchestrator._dependency_counter = itertools.count(counters.get("dependency", 1)); workflow_engine._review_counter = itertools.count(counters.get("review", 1)); workflow_engine._conflict_counter = itertools.count(counters.get("conflict", 1)); notification_manager._counter = itertools.count(counters.get("notification", 1))
