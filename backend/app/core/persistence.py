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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, delete, func, or_, select, update as sql_update
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
MIGRATION_HEAD = "0014_documents"


class Base(DeclarativeBase):
    pass


class ApplicationRow(Base):
    __tablename__ = "applications"
    app_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    authoritative_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class DependencyRow(Base):
    __tablename__ = "dependencies"
    dependency_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.app_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    required_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    payload: Mapped[dict] = mapped_column(JSONB)


class ConsentRow(Base):
    __tablename__ = "consents"
    consent_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(120), index=True)
    app_id: Mapped[Optional[str]] = mapped_column(ForeignKey("applications.app_id", ondelete="SET NULL"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
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
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_dispatched_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dispatch_claimed_until: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    lease_until: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
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


class CitizenRow(Base):
    """Platform-level citizen/identity master record.

    This is SANGAM's own minimal identity index (name, DOB, phone, district) used
    to seed a consistent synthetic citizen across independently simulated
    department sandboxes. It is not a copy of any department's records.
    """
    __tablename__ = "citizens"
    citizen_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str] = mapped_column(String(20))
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    persona: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class RequirementCatalogRow(Base):
    """Canonical requirement catalog. requirement_code values used by
    ServiceCatalogRow/SchemeRequirementRow reference this table by convention.
    """
    __tablename__ = "requirements"
    requirement_code: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    data_type: Mapped[str] = mapped_column(String(40), default="DOCUMENT")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class SchemaMappingRow(Base):
    """Department field -> SANGAM canonical field mapping for one provider/service.

    Department systems are never forced onto SANGAM's schema; this row records
    how a specific provider's field names translate to canonical requirement
    attributes so adapters can normalize responses.
    """
    __tablename__ = "schema_mappings"
    mapping_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id", ondelete="CASCADE"), index=True)
    service_id: Mapped[Optional[str]] = mapped_column(ForeignKey("service_catalog.service_id", ondelete="CASCADE"), nullable=True, index=True)
    department_field: Mapped[str] = mapped_column(String(200))
    canonical_field: Mapped[str] = mapped_column(String(200), index=True)
    data_type: Mapped[str] = mapped_column(String(40), default="string")
    transform: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class DocumentRow(Base):
    """A document/artifact reference -- metadata and lifecycle state for an
    artifact retrieved from a provider or uploaded by a citizen. This is a
    reference/metadata record, not a copy of a department's authoritative
    document; app_id/dependency_id are deliberately unconstrained (see
    migration 0014) because the workflow they describe may still be
    in-flight, in-memory state at the moment this row is written.
    """
    __tablename__ = "documents"
    document_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(120), index=True)
    dependency_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    requirement_code: Mapped[str] = mapped_column(String(120), index=True)
    citizen_id: Mapped[str] = mapped_column(String(120), index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("providers.provider_id", ondelete="SET NULL"), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    reference_uri: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    validation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)


def _document_payload(row: DocumentRow) -> dict:
    payload = dict(row.payload or {})
    payload.update({
        "documentId": row.document_id, "appId": row.app_id, "dependencyId": row.dependency_id,
        "requirementCode": row.requirement_code, "citizenId": row.citizen_id, "sourceType": row.source_type,
        "providerId": row.provider_id, "documentType": row.document_type, "status": row.status,
        "checksum": row.checksum, "isSynthetic": row.is_synthetic, "referenceUri": row.reference_uri,
        "validation": row.validation,
    })
    return payload


def upsert_document(document: Mapping) -> dict:
    """Create or update one document/reference row (get-or-create + update)."""
    with Session(engine) as session:
        row = session.get(DocumentRow, document["documentId"])
        now = datetime.now(timezone.utc)
        values = dict(
            app_id=document["appId"], dependency_id=document.get("dependencyId"),
            requirement_code=document["requirementCode"], citizen_id=document["citizenId"],
            source_type=document["sourceType"], provider_id=document.get("providerId"),
            document_type=document.get("documentType", document["requirementCode"]),
            status=document["status"], checksum=document.get("checksum"),
            is_synthetic=document.get("isSynthetic", True), reference_uri=document.get("referenceUri"),
            validation=document.get("validation"), updated_at=now, payload=dict(document),
        )
        if row is None:
            session.add(DocumentRow(document_id=document["documentId"], created_at=now, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.commit()
    return document


def get_document(document_id: str, session: Session | None = None) -> dict | None:
    def read(db_session: Session) -> dict | None:
        row = db_session.get(DocumentRow, document_id)
        return _document_payload(row) if row else None
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def list_documents_for_application(app_id: str, session: Session | None = None) -> list[dict]:
    def read(db_session: Session) -> list[dict]:
        rows = db_session.query(DocumentRow).filter_by(app_id=app_id).order_by(DocumentRow.document_id.asc()).all()
        return [_document_payload(row) for row in rows]
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def _application_payload(row: ApplicationRow) -> dict:
    payload = dict(row.payload or {})
    payload["appId"] = row.app_id
    payload["citizenId"] = row.citizen_id
    payload["status"] = row.status
    return payload


class ApplicationConcurrencyError(RuntimeError):
    """Raised when an application write was based on a stale version."""


class ApplicationAuthorityError(RuntimeError):
    """Raised when a legacy writer targets a PostgreSQL-authoritative app."""


class ConsentConcurrencyError(RuntimeError):
    """Raised when a consent snapshot is based on a stale PostgreSQL version."""


def assert_legacy_application_writable(app_id: str) -> None:
    """Advisory preflight for legacy callers; persist_transition is definitive."""
    with Session(engine) as session:
        try:
            row = session.execute(
                select(ApplicationRow).where(ApplicationRow.app_id == app_id).with_for_update()
            ).scalar_one_or_none()
            if row is not None and row.authoritative_at is not None:
                raise ApplicationAuthorityError("Application changed concurrently; please reload and retry.")
            session.commit()
        except Exception:
            session.rollback()
            raise


def _application_timestamp(value: str | datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid application {field_name} timestamp") from error
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)


def _application_iso(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat()


def _run_application_owned(operation):
    with Session(engine) as owned_session:
        try:
            result = operation(owned_session)
            owned_session.commit()
            return result
        except Exception:
            owned_session.rollback()
            raise


def _application_result(row: ApplicationRow) -> dict:
    return _application_payload(row)


def allocate_application_id(service_id: str | None = None, session: Session | None = None) -> str:
    """Allocate an application identifier under a PostgreSQL row lock."""
    def allocate(db_session: Session) -> str:
        from sqlalchemy.dialects.postgresql import insert as postgres_insert

        db_session.execute(
            postgres_insert(CounterRow)
            .values(counter_key="application", next_value=142)
            .on_conflict_do_nothing(index_elements=[CounterRow.counter_key])
        )
        counter = db_session.execute(
            select(CounterRow).where(CounterRow.counter_key == "application").with_for_update()
        ).scalar_one()
        value = counter.next_value
        prefix = "SCH-MH-2026" if service_id == "SCH-MH-2026" else f"APP-{service_id or 'SERVICE'}"
        while True:
            app_id = f"{prefix}-{value:05d}"
            if db_session.get(ApplicationRow, app_id) is None:
                counter.next_value = value + 1
                db_session.flush()
                return app_id
            value += 1

    if session is not None:
        return allocate(session)
    return _run_application_owned(allocate)


def create_application(application: Mapping, session: Session | None = None) -> dict:
    """Create an application row using PostgreSQL as the write authority."""
    def create(db_session: Session) -> dict:
        payload = dict(application)
        citizen_id = payload.get("citizenId")
        status = payload.get("status", "DRAFT")
        if not citizen_id:
            raise ValueError("Application requires citizenId")
        app_id = payload.get("appId") or allocate_application_id(payload.get("serviceId"), session=db_session)
        created_at = _application_timestamp(payload.get("createdAt"), "createdAt") or datetime.now(timezone.utc)
        updated_at = _application_timestamp(payload.get("updatedAt"), "updatedAt") or created_at
        payload["appId"] = app_id
        payload["citizenId"] = citizen_id
        payload["status"] = status
        payload["createdAt"] = _application_iso(created_at)
        payload["updatedAt"] = _application_iso(updated_at)
        row = ApplicationRow(
            app_id=app_id,
            citizen_id=citizen_id,
            status=status,
            version=1,
            created_at=created_at,
            updated_at=updated_at,
            authoritative_at=datetime.now(timezone.utc),
            payload=payload,
        )
        db_session.add(row)
        db_session.flush()
        return _application_result(row)

    if session is not None:
        return create(session)
    return _run_application_owned(create)


_APPLICATION_MUTATION_RESERVED_FIELDS = frozenset({
    "appId", "citizenId", "status", "version", "createdAt", "updatedAt", "authoritativeAt",
    "app_id", "citizen_id", "created_at", "updated_at", "authoritative_at",
})


def mutate_application(app_id: str, patch: Mapping, expected_version: int | None = None, session: Session | None = None) -> dict:
    """Mutate application JSONB payload fields in a caller-owned transaction.

    This is a database-only authority boundary. It deliberately does not touch
    process-local workflow dictionaries or invoke any legacy persistence or
    side-effect mechanism. A caller-owned session controls commit/rollback and
    therefore the lifetime of the row lock and the authority marker.
    """
    if not isinstance(patch, Mapping):
        raise TypeError("Application mutation patch must be a mapping")
    forbidden = _APPLICATION_MUTATION_RESERVED_FIELDS.intersection(patch)
    if forbidden:
        raise ValueError(f"Application mutation cannot update {', '.join(sorted(forbidden))}")

    def update(db_session: Session) -> dict:
        row = db_session.execute(
            select(ApplicationRow).where(ApplicationRow.app_id == app_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(app_id)
        if expected_version is not None and row.version != expected_version:
            raise ApplicationConcurrencyError(f"Application {app_id} has version {row.version}, expected {expected_version}")
        payload = dict(row.payload or {})
        payload.update(dict(patch))
        now = datetime.now(timezone.utc)
        payload["appId"] = row.app_id
        payload["citizenId"] = row.citizen_id
        payload["status"] = row.status
        payload["createdAt"] = _application_iso(row.created_at or now)
        payload["updatedAt"] = _application_iso(now)
        row.payload = payload
        row.updated_at = now
        row.authoritative_at = row.authoritative_at or now
        row.version += 1
        db_session.flush()
        return _application_result(row)

    if session is not None:
        return update(session)
    return _run_application_owned(update)


def update_application_payload(app_id: str, patch: Mapping, expected_version: int | None = None, session: Session | None = None) -> dict:
    """Compatibility name for the PostgreSQL-authoritative mutation gateway."""
    return mutate_application(app_id, patch, expected_version=expected_version, session=session)


def transition_application_status(app_id: str, status: str, actor: str = "SYSTEM", source: str = "workflow_engine", expected_version: int | None = None, session: Session | None = None) -> dict:
    """Transition an application and append history in one caller-scoped transaction."""
    def transition(db_session: Session) -> dict:
        from app.engine.workflow_engine import CANONICAL_STATUSES, VALID_TRANSITIONS

        row = db_session.execute(
            select(ApplicationRow).where(ApplicationRow.app_id == app_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(app_id)
        if expected_version is not None and row.version != expected_version:
            raise ApplicationConcurrencyError(f"Application {app_id} has version {row.version}, expected {expected_version}")
        if status not in CANONICAL_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        previous = row.status
        if previous == status:
            return _application_result(row)
        if status not in VALID_TRANSITIONS.get(previous, set()):
            raise ValueError(f"Invalid application transition: {previous} -> {status}")
        timestamp = datetime.now(timezone.utc)
        timestamp_iso = _application_iso(timestamp)
        history_entry = {"status": status, "at": timestamp_iso, "actor": actor, "source": source}
        payload = dict(row.payload or {})
        payload["appId"] = row.app_id
        payload["citizenId"] = row.citizen_id
        payload["status"] = status
        payload["updatedAt"] = timestamp_iso
        payload["createdAt"] = _application_iso(row.created_at) if row.created_at else payload.get("createdAt", timestamp_iso)
        row.status = status
        row.updated_at = timestamp
        row.authoritative_at = row.authoritative_at or timestamp
        row.version += 1
        row.payload = payload
        db_session.add(WorkflowHistoryRow(app_id=app_id, status=status, occurred_at=timestamp_iso, payload=history_entry))
        db_session.flush()
        return _application_result(row)

    if session is not None:
        return transition(session)
    return _run_application_owned(transition)


_WORKFLOW_CHILD_MODELS = {
    "dependency": DependencyRow,
    "entity_review": EntityReviewRow,
    "conflict_review": ConflictReviewRow,
}
_WORKFLOW_CHILD_ID_FIELDS = {
    "dependency": DependencyRow.dependency_id,
    "entity_review": EntityReviewRow.review_id,
    "conflict_review": ConflictReviewRow.review_id,
}
_WORKFLOW_CHILD_RESERVED_FIELDS = frozenset({
    "appId", "app_id", "dependencyId", "dependency_id", "reviewId", "review_id",
    "version", "createdAt", "created_at",
})
_DEPENDENCY_TYPED_FIELDS = {
    "status": "status",
    "requiredData": "required_data",
    "required_data": "required_data",
    "jobId": "job_id",
    "job_id": "job_id",
    "jobStatus": "job_status",
    "job_status": "job_status",
    "resultReference": "result_reference",
    "result_reference": "result_reference",
    "attempts": "attempts",
    "maxAttempts": "max_attempts",
    "max_attempts": "max_attempts",
}


def _workflow_child_result(row) -> dict:
    if isinstance(row, DependencyRow):
        return _dependency_payload(row)
    payload = dict(row.payload or {})
    payload["reviewId"] = row.review_id
    payload["appId"] = row.app_id
    return payload


def _workflow_child_query(db_session: Session, child_kind: str, child_id: str, for_update: bool):
    model = _WORKFLOW_CHILD_MODELS[child_kind]
    query = select(model).where(_WORKFLOW_CHILD_ID_FIELDS[child_kind] == child_id)
    if for_update:
        query = query.with_for_update()
    return db_session.execute(query).scalar_one_or_none()


def _workflow_aggregate_result(app_row: ApplicationRow, child_row=None) -> dict:
    """Return domain payloads plus internal concurrency metadata."""
    return {
        "application": _application_result(app_row),
        "application_version": app_row.version,
        "child": _workflow_child_result(child_row) if child_row else None,
    }


def load_workflow_aggregate(
    app_id: str | None,
    *,
    session: Session,
    child_kind: str | None = None,
    child_id: str | None = None,
    for_update: bool = False,
) -> dict | None:
    """Load an application aggregate and optional child from PostgreSQL.

    When requested, locks are acquired in the same application-first order as
    ``mutate_workflow_aggregate``.  The caller owns the transaction.
    """
    if app_id is None:
        if child_kind not in _WORKFLOW_CHILD_MODELS or not child_id:
            raise ValueError("app_id or a valid child selector is required")
        child_model = _WORKFLOW_CHILD_MODELS[child_kind]
        app_id = session.execute(
            select(child_model.app_id).where(_WORKFLOW_CHILD_ID_FIELDS[child_kind] == child_id)
        ).scalar_one_or_none()
        if app_id is None:
            return None
    app_query = select(ApplicationRow).where(ApplicationRow.app_id == app_id)
    if for_update:
        app_query = app_query.with_for_update()
    app_row = session.execute(app_query).scalar_one_or_none()
    if app_row is None:
        return None
    child_row = None
    if child_kind is not None:
        if child_kind not in _WORKFLOW_CHILD_MODELS or not child_id:
            raise ValueError("A valid child_kind and child_id are required")
        child_row = _workflow_child_query(session, child_kind, child_id, for_update)
        if child_row is None or child_row.app_id != app_id:
            return None
    return _workflow_aggregate_result(app_row, child_row)


def mutate_workflow_aggregate(
    app_id: str,
    *,
    expected_version: int,
    session: Session,
    application_patch: Mapping | None = None,
    status: str | None = None,
    actor: str = "SYSTEM",
    source: str = "workflow_boundary",
    child_kind: str | None = None,
    child_id: str | None = None,
    child_patch: Mapping | None = None,
) -> dict:
    """Mutate one application aggregate in a caller-owned transaction.

    The application row is always locked first, followed by at most one child
    row.  This function only flushes; the caller owns commit/rollback and may
    therefore keep all locks until the aggregate mutation is durable.  It does
    not touch workflow dictionaries or publish side effects.
    """
    if not session.in_transaction():
        raise RuntimeError("Workflow aggregate mutation requires an active caller-owned transaction")
    if not isinstance(expected_version, int):
        raise TypeError("expected_version is required")
    application_patch = dict(application_patch or {})
    forbidden = _APPLICATION_MUTATION_RESERVED_FIELDS.union({"statusHistory", "status_history"}).intersection(application_patch)
    if forbidden:
        raise ValueError(f"Workflow mutation cannot update {', '.join(sorted(forbidden))}")
    if child_kind is not None:
        if child_kind not in _WORKFLOW_CHILD_MODELS:
            raise ValueError(f"Unsupported workflow child kind: {child_kind}")
        if not child_id:
            raise ValueError("child_id is required when child_kind is supplied")
    elif child_id is not None or child_patch is not None:
        raise ValueError("child_kind is required for child mutations")
    child_patch = dict(child_patch or {})
    if _WORKFLOW_CHILD_RESERVED_FIELDS.intersection(child_patch):
        raise ValueError("Workflow child identity/version fields are immutable")

    from app.engine.workflow_engine import CANONICAL_STATUSES, VALID_TRANSITIONS

    app_row = session.execute(
        select(ApplicationRow).where(ApplicationRow.app_id == app_id).with_for_update()
    ).scalar_one_or_none()
    if app_row is None:
        raise KeyError(app_id)
    if app_row.version != expected_version:
        raise ApplicationConcurrencyError(f"Application {app_id} has version {app_row.version}, expected {expected_version}")

    child_row = None
    if child_kind is not None:
        child_row = _workflow_child_query(session, child_kind, child_id, True)
        if child_row is None or child_row.app_id != app_id:
            raise KeyError(child_id)

    previous_status = app_row.status
    if status is not None:
        if status not in CANONICAL_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        if previous_status != status and status not in VALID_TRANSITIONS.get(previous_status, set()):
            raise ValueError(f"Invalid application transition: {previous_status} -> {status}")

    now = datetime.now(timezone.utc)
    timestamp_iso = _application_iso(now)
    payload = dict(app_row.payload or {})
    payload_changed = False
    for key, value in application_patch.items():
        if payload.get(key) != value:
            payload[key] = value
            payload_changed = True

    status_changed = status is not None and status != previous_status
    if status_changed:
        payload["status"] = status
        history_entry = {"status": status, "at": timestamp_iso, "actor": actor, "source": source}
        status_history = list(payload.get("statusHistory") or [])
        status_history.append(history_entry)
        payload["statusHistory"] = status_history
        payload_changed = True

    child_changed = False
    if child_row is not None:
        if isinstance(child_row, DependencyRow):
            child_payload = dict(child_row.payload or {})
            for key, value in child_patch.items():
                if key in _DEPENDENCY_TYPED_FIELDS:
                    field = _DEPENDENCY_TYPED_FIELDS[key]
                    if getattr(child_row, field) != value:
                        setattr(child_row, field, value)
                        child_changed = True
                    canonical_key = {
                        "required_data": "requiredData", "job_id": "jobId", "job_status": "jobStatus",
                        "result_reference": "resultReference", "max_attempts": "maxAttempts",
                    }.get(field, field)
                    child_payload[canonical_key] = value
                elif child_payload.get(key) != value:
                    child_payload[key] = value
                    child_changed = True
            if child_changed:
                child_row.payload = child_payload
                child_row.updated_at = now
                child_row.version += 1
        else:
            child_payload = dict(child_row.payload or {})
            for key, value in child_patch.items():
                if child_payload.get(key) != value:
                    child_payload[key] = value
                    child_changed = True
            if child_changed:
                child_row.payload = child_payload

    aggregate_changed = payload_changed or child_changed
    if not aggregate_changed:
        result = _workflow_aggregate_result(app_row, child_row)
        result["post_commit_refresh"] = (app_id, child_kind, child_id)
        return result

    payload["appId"] = app_row.app_id
    payload["citizenId"] = app_row.citizen_id
    payload["status"] = status if status is not None else app_row.status
    payload["createdAt"] = _application_iso(app_row.created_at) if app_row.created_at else payload.get("createdAt", timestamp_iso)
    payload["updatedAt"] = timestamp_iso
    app_row.status = status if status is not None else app_row.status
    app_row.payload = payload
    app_row.updated_at = now
    app_row.authoritative_at = app_row.authoritative_at or now
    app_row.version += 1
    if status_changed:
        session.add(WorkflowHistoryRow(app_id=app_id, status=status, occurred_at=timestamp_iso, payload=history_entry))
    session.flush()
    result = _workflow_aggregate_result(app_row, child_row)
    result["post_commit_refresh"] = (app_id, child_kind, child_id)
    return result


def refresh_workflow_aggregate(app_id: str, child_kind: str | None = None, child_id: str | None = None, session: Session | None = None) -> dict:
    """Read the committed aggregate for use after the caller commits."""
    def read(db_session: Session) -> dict:
        app_row = db_session.execute(select(ApplicationRow).where(ApplicationRow.app_id == app_id)).scalar_one_or_none()
        if app_row is None:
            return {"application": None, "child": None}
        child_row = None
        if child_kind is not None:
            if child_kind not in _WORKFLOW_CHILD_MODELS or not child_id:
                raise ValueError("A valid child_kind and child_id are required")
            child_row = _workflow_child_query(db_session, child_kind, child_id, False)
            if child_row is None or child_row.app_id != app_id:
                return {"application": _application_result(app_row), "application_version": app_row.version, "child": None}
        return _workflow_aggregate_result(app_row, child_row)
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def mark_application_write_authoritative(request) -> None:
    """Mark only this request to bypass destructive legacy snapshot persistence."""
    request.state.application_write_authoritative = True


def _dependency_payload(row: DependencyRow) -> dict:
    payload = dict(row.payload or {})
    payload["dependencyId"] = row.dependency_id
    payload["appId"] = row.app_id
    payload["status"] = row.status
    return payload


def get_application(app_id: str, for_update: bool = False, session: Session | None = None) -> dict | None:
    """Read one application directly from PostgreSQL.

    Database errors intentionally propagate. No process-local workflow cache is
    consulted, and the optional lock is held only for this database transaction.
    """
    def read(db_session: Session) -> dict | None:
        query = db_session.query(ApplicationRow).filter(ApplicationRow.app_id == app_id)
        if for_update:
            query = query.with_for_update()
        row = query.first()
        return _application_payload(row) if row else None
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def list_applications_for_citizen(citizen_id: str, session: Session | None = None) -> list[dict]:
    """Read all applications for a citizen directly from PostgreSQL."""
    def read(db_session: Session) -> list[dict]:
        rows = (db_session.query(ApplicationRow)
                .filter(ApplicationRow.citizen_id == citizen_id)
                .order_by(ApplicationRow.app_id.asc())
                .all())
        return [_application_payload(row) for row in rows]
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def get_dependency(dependency_id: str, for_update: bool = False, session: Session | None = None) -> dict | None:
    """Read one dependency directly from PostgreSQL."""
    def read(db_session: Session) -> dict | None:
        query = db_session.query(DependencyRow).filter(DependencyRow.dependency_id == dependency_id)
        if for_update:
            query = query.with_for_update()
        row = query.first()
        return _dependency_payload(row) if row else None
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def list_dependencies_for_application(app_id: str, session: Session | None = None) -> list[dict]:
    """Read all dependencies for an application directly from PostgreSQL."""
    def read(db_session: Session) -> list[dict]:
        rows = (db_session.query(DependencyRow)
                .filter(DependencyRow.app_id == app_id)
                .order_by(DependencyRow.dependency_id.asc())
                .all())
        return [_dependency_payload(row) for row in rows]
    if session is not None:
        return read(session)
    with Session(engine) as owned_session:
        return read(owned_session)


def initialize() -> None:
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
        if version != MIGRATION_HEAD:
            raise RuntimeError(f"Database schema is at migration {version!r}; run 'alembic upgrade head' before starting SANGAM.")
    except Exception as error:
            raise RuntimeError(f"PostgreSQL initialization failed: {error}") from error


def validate_production_configuration() -> None:
    """Reject development/demo defaults when explicitly running in production."""
    mode = os.getenv("SANGAM_ENV", "development").strip().lower()
    if mode not in {"production", "prod"}:
        return
    if (os.getenv("SANGAM_SEED_CATALOG", "false").lower() in {"1", "true", "yes"}
            or os.getenv("SANGAM_SEED_DEMO_USERS", "false").lower() in {"1", "true", "yes"}
            or os.getenv("SANGAM_SEED_SYNTHETIC_DATA", "false").lower() in {"1", "true", "yes"}
            or os.getenv("SANGAM_SEED_DEPARTMENT_PROVIDERS", "false").lower() in {"1", "true", "yes"}):
        raise RuntimeError("Demo catalog/user seeding (including synthetic data) must be disabled in production.")
    origins = [item.strip().lower() for item in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if item.strip()]
    if not origins or "*" in origins or any("localhost" in item or "127.0.0.1" in item for item in origins):
        raise RuntimeError("Production requires explicit non-local CORS_ALLOWED_ORIGINS.")
    with Session(engine) as session:
        sandbox = session.query(ProviderRow).filter(ProviderRow.active.is_(True), ProviderRow.environment != "PRODUCTION").count()
    if sandbox:
        raise RuntimeError("Production cannot start with active non-PRODUCTION providers.")


def _job_from_row(row: ProviderJobRow) -> dict:
    return {"jobId": row.job_id, "jobType": row.job_type, "status": row.status,
            "correlationId": row.correlation_id, "applicationId": row.application_id,
            "dependencyId": row.dependency_id, "providerId": row.provider_id,
            "attempt": row.attempt, "maxAttempts": row.max_attempts,
            "createdAt": row.created_at, "startedAt": row.started_at,
            "completedAt": row.completed_at, "error": ({"category": row.error_category, "message": row.error_message} if row.error_category else None),
            "payload": row.payload or {}, "dispatchAttempts": row.dispatch_attempts,
            "lastDispatchedAt": row.last_dispatched_at, "dispatchClaimedUntil": row.dispatch_claimed_until,
            "leaseOwner": row.lease_owner, "leaseUntil": row.lease_until}


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
                  "dispatch_attempts": job.get("dispatchAttempts", 0), "last_dispatched_at": job.get("lastDispatchedAt"),
                  "dispatch_claimed_until": job.get("dispatchClaimedUntil"),
                  "lease_owner": job.get("leaseOwner"), "lease_until": job.get("leaseUntil"),
                  "error_category": error.get("category"), "error_message": safe_error_message(error.get("message", "")) or None,
                  "payload": job.get("payload") or {}}
        if row is None:
            session.add(ProviderJobRow(job_id=job["jobId"], **values))
        else:
            for key, value in values.items(): setattr(row, key, value)
        session.commit()
    return job


def claim_provider_job(job_id: str, worker_id: str | None = None, lease_seconds: int = 60) -> dict | None:
    """Atomically claim only a queued job; duplicate deliveries become no-ops."""
    with Session(engine) as session:
        row = session.execute(select(ProviderJobRow).where(ProviderJobRow.job_id == job_id).with_for_update()).scalar_one_or_none()
        if row is None or row.status != "QUEUED":
            return None
        row.status = "RUNNING"
        row.attempt += 1
        row.started_at = datetime.now(timezone.utc).isoformat()
        row.lease_owner = worker_id or "anonymous-worker"
        row.lease_until = (datetime.now(timezone.utc) + timedelta(seconds=max(15, min(lease_seconds, 600)))).isoformat()
        row.dispatch_claimed_until = None
        session.commit()
        return _job_from_row(row)


def update_provider_job(job: dict) -> dict | None:
    """Apply a worker result only while its PostgreSQL lease is still current."""
    with Session(engine) as session:
        status = job["status"]
        values = {"status": status, "attempt": job.get("attempt"), "started_at": job.get("startedAt"), "completed_at": job.get("completedAt")}
        if status == "QUEUED":
            values.update(last_dispatched_at=None, dispatch_claimed_until=None, lease_owner=None, lease_until=None)
        elif status in {"COMPLETED", "FAILED", "DEAD_LETTER"}:
            values.update(lease_owner=None, lease_until=None)
        error = job.get("error") or {}
        from app.core.job_queue import safe_error_message
        values["error_category"] = error.get("category")
        values["error_message"] = safe_error_message(error.get("message", "")) or None
        now_iso = datetime.now(timezone.utc).isoformat()
        result = session.execute(
            sql_update(ProviderJobRow)
            .where(ProviderJobRow.job_id == job["jobId"])
            .where(ProviderJobRow.status == "RUNNING")
            .where(ProviderJobRow.attempt == job.get("attempt"))
            .where(ProviderJobRow.lease_owner == job.get("leaseOwner"))
            .where(ProviderJobRow.lease_until.is_not(None))
            .where(ProviderJobRow.lease_until > now_iso)
            .values(**values)
        )
        if result.rowcount != 1:
            session.rollback()
            return None
        session.commit()
    return job


def recover_provider_jobs() -> list[dict]:
    """Turn abandoned RUNNING jobs back into queued work after a restart."""
    recovered = []
    with Session(engine) as session:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = session.execute(
            select(ProviderJobRow)
            .where(ProviderJobRow.status == "RUNNING")
            .where(ProviderJobRow.lease_until.is_not(None))
            .where(ProviderJobRow.lease_until <= now_iso)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for row in rows:
            row.status = "QUEUED"
            row.started_at = None
            row.last_dispatched_at = None
            row.dispatch_claimed_until = None
            row.lease_owner = None
            row.lease_until = None
            recovered.append(_job_from_row(row))
        session.commit()
    return recovered


def claim_queued_provider_jobs(limit: int = 25, lease_seconds: int = 30) -> list[dict]:
    """Lease a bounded batch of queued jobs for Redis dispatch.

    The lease is database-backed and short-lived. If a process dies after
    Redis accepts a message but before the marker is cleared, the job becomes
    eligible again; PostgreSQL claim remains the execution idempotency guard.
    """
    from datetime import timedelta
    now_value = datetime.now(timezone.utc)
    now_iso = now_value.isoformat()
    lease_until = (now_value + timedelta(seconds=max(5, min(lease_seconds, 300)))).isoformat()
    with Session(engine) as session:
        rows = session.execute(
            select(ProviderJobRow)
            .where(ProviderJobRow.status == "QUEUED")
            .where(
                (ProviderJobRow.dispatch_claimed_until.is_(None) |
                 (ProviderJobRow.dispatch_claimed_until <= now_iso))
            )
            .order_by(ProviderJobRow.created_at.asc())
            .limit(max(1, min(limit, 100)))
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for row in rows:
            row.dispatch_attempts += 1
            row.dispatch_claimed_until = lease_until
        session.commit()
        return [_job_from_row(row) for row in rows]


def mark_provider_job_dispatched(job_id: str) -> None:
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job_id)
        if row and row.status == "QUEUED":
            row.last_dispatched_at = datetime.now(timezone.utc).isoformat()
            row.dispatch_claimed_until = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
            session.commit()


def release_provider_job_dispatch(job_id: str) -> None:
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job_id)
        if row and row.status == "QUEUED":
            row.dispatch_claimed_until = None
            session.commit()


def renew_provider_job_lease(job_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
    with Session(engine) as session:
        row = session.get(ProviderJobRow, job_id, with_for_update=True)
        if not row or row.status != "RUNNING" or row.lease_owner != worker_id:
            return False
        row.lease_until = (datetime.now(timezone.utc) + timedelta(seconds=max(15, min(lease_seconds, 600)))).isoformat()
        session.commit()
        return True


def persist_consent(receipt: dict) -> dict:
    with Session(engine) as session:
        row = session.get(ConsentRow, receipt["consentId"], with_for_update=True)
        app_id = receipt.get("applicationId")
        if app_id and session.get(ApplicationRow, app_id) is None:
            app_id = None
        if row is None:
            row = ConsentRow(consent_id=receipt["consentId"], citizen_id=receipt["citizenId"], app_id=app_id, version=1, payload={key: value for key, value in receipt.items() if key != "_source_version"})
            session.add(row)
            new_version = 1
        else:
            row.citizen_id = receipt["citizenId"]
            row.app_id = app_id
            row.payload = {key: value for key, value in receipt.items() if key != "_source_version"}
            row.version += 1
            new_version = row.version
        session.commit()
    receipt["_source_version"] = new_version
    from app.engine import consent_manager
    consent_manager.CONSENT_SOURCE_VERSIONS[receipt["consentId"]] = new_version
    return receipt


def revoke_persisted_consent(citizen_id: str, consent_id: str) -> dict:
    with Session(engine) as session:
        row = session.execute(
            select(ConsentRow).where(ConsentRow.consent_id == consent_id, ConsentRow.citizen_id == citizen_id).with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(consent_id)
        receipt = dict(row.payload or {})
        receipt["decision"] = "REVOKED"
        receipt["allowed"] = []
        receipt["revokedAt"] = datetime.now(timezone.utc).isoformat()
        row.payload = {key: value for key, value in receipt.items() if key != "_source_version"}
        row.version += 1
        new_version = row.version
        session.commit()
        receipt["_source_version"] = new_version
        from app.engine import consent_manager
        consent_manager.CONSENT_SOURCE_VERSIONS[consent_id] = new_version
        return receipt


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
            existing_scheme = session.get(SchemeCatalogRow, scheme["id"])
            if existing_scheme is None:
                session.add(SchemeCatalogRow(scheme_id=scheme["id"], name=scheme["name"], department=department, payload=scheme))
                for requirement in scheme.get("requirements", []):
                    session.add(SchemeRequirementRow(scheme_id=scheme["id"], requirement_code=requirement["code"], label=requirement["label"], mandatory=requirement.get("mandatory", True), payload=requirement))
            else:
                existing_scheme.payload = {**(existing_scheme.payload or {}), **scheme}
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


REQUIREMENT_CATALOG = [
    {"code": "IDENTITY", "name": "Identity", "category": "IDENTITY", "dataType": "ATTRIBUTE", "description": "Citizen identity as held by the federated identity source."},
    {"code": "INCOME_PROOF", "name": "Income proof", "category": "REVENUE", "dataType": "CERTIFICATE", "description": "Annual family income as certified by the Revenue Department."},
    {"code": "DOMICILE_PROOF", "name": "Maharashtra domicile", "category": "REVENUE", "dataType": "CERTIFICATE", "description": "Domicile/residency certificate issued by the Revenue Department."},
    {"code": "LAND_HOLDING", "name": "Land holding record", "category": "REVENUE", "dataType": "RECORD", "description": "7/12 extract style land holding record."},
    {"code": "CASTE_PROOF", "name": "Caste proof", "category": "SOCIAL_WELFARE", "dataType": "CERTIFICATE", "description": "Caste certificate as verified by the Social Welfare Department."},
    {"code": "BANK_DETAILS", "name": "DBT bank status", "category": "SOCIAL_WELFARE", "dataType": "RECORD", "description": "Direct benefit transfer bank-linkage status."},
    {"code": "SCHEME_ENROLLMENT_STATUS", "name": "Welfare scheme enrollment", "category": "SOCIAL_WELFARE", "dataType": "RECORD", "description": "Enrollment status in a Social Welfare Department scheme."},
    {"code": "ACADEMIC_RECORD", "name": "Academic record", "category": "EDUCATION", "dataType": "RECORD", "description": "Academic/enrollment record from the Education Department."},
    {"code": "SCHOLARSHIP_ELIGIBILITY", "name": "Scholarship eligibility", "category": "EDUCATION", "dataType": "RECORD", "description": "Scholarship eligibility assessment from the Education Department."},
    {"code": "FARMER_REGISTRATION", "name": "Farmer registration", "category": "AGRICULTURE", "dataType": "RECORD", "description": "Registered farmer identity with the Agriculture Department."},
    {"code": "CROP_LOAN_STATUS", "name": "Crop loan status", "category": "AGRICULTURE", "dataType": "RECORD", "description": "Outstanding/settled crop loan status."},
    {"code": "VEHICLE_REGISTRATION", "name": "Vehicle registration", "category": "TRANSPORT", "dataType": "RECORD", "description": "RTO vehicle registration record."},
    {"code": "DRIVING_LICENCE", "name": "Driving licence", "category": "TRANSPORT", "dataType": "CERTIFICATE", "description": "Driving licence issued by the RTO."},
    {"code": "WORKER_REGISTRATION", "name": "Worker registration", "category": "LABOUR", "dataType": "RECORD", "description": "Registered construction/unorganized worker record."},
    {"code": "WELFARE_BOARD_MEMBERSHIP", "name": "Welfare board membership", "category": "LABOUR", "dataType": "RECORD", "description": "Labour welfare board membership status."},
    {"code": "RATION_CARD", "name": "Ration card", "category": "FOOD_CIVIL_SUPPLIES", "dataType": "CERTIFICATE", "description": "Public distribution system ration card."},
    {"code": "HOUSING_ALLOTMENT", "name": "Housing allotment", "category": "HOUSING", "dataType": "RECORD", "description": "Public housing scheme allotment/waitlist status."},
    {"code": "SKILL_CERTIFICATION", "name": "Skill certification", "category": "SKILL_EMPLOYMENT", "dataType": "CERTIFICATE", "description": "Skill development certification record."},
    {"code": "EMPLOYMENT_REGISTRATION", "name": "Employment exchange registration", "category": "SKILL_EMPLOYMENT", "dataType": "RECORD", "description": "Jobseeker registration with the employment exchange."},
    {"code": "BIRTH_CERTIFICATE", "name": "Birth certificate", "category": "MUNICIPAL_HEALTH", "dataType": "CERTIFICATE", "description": "Municipal birth registration certificate."},
    {"code": "IMMUNIZATION_RECORD", "name": "Immunization record", "category": "MUNICIPAL_HEALTH", "dataType": "RECORD", "description": "Public health immunization record."},
]


def requirement_catalog_seeded() -> bool:
    with Session(engine) as session:
        return session.query(RequirementCatalogRow).count() > 0


def seed_requirement_catalog() -> None:
    """Bootstrap the canonical requirement vocabulary once; DB-owned afterwards.

    This is reference/vocabulary data only. It does not create providers,
    services, or capabilities for the department sandboxes -- wiring a
    department sandbox into SANGAM's dynamic provider/capability model is
    deliberately out of scope for the database foundation phase.
    """
    if os.getenv("SANGAM_SEED_CATALOG", "false").lower() not in {"1", "true", "yes"}:
        return
    with Session(engine) as session:
        for requirement in REQUIREMENT_CATALOG:
            if session.get(RequirementCatalogRow, requirement["code"]) is not None:
                continue
            session.add(RequirementCatalogRow(
                requirement_code=requirement["code"],
                name=requirement["name"],
                description=requirement.get("description"),
                category=requirement.get("category"),
                data_type=requirement.get("dataType", "DOCUMENT"),
                payload=requirement,
            ))
        session.commit()


def seed_schema_mappings() -> None:
    """Bootstrap department-field -> canonical-field mappings for existing providers.

    Scoped to providers already registered in the SANGAM catalog (seeded by
    ``seed_catalog``); simulated department sandboxes are not yet registered as
    providers, so they have no mappings until a future integration phase.
    """
    if os.getenv("SANGAM_SEED_CATALOG", "false").lower() not in {"1", "true", "yes"}:
        return
    mappings = [
        {"provider": "REVENUE-DEPARTMENT", "service": "REV-INCOME-102", "field": "annual_income", "canonical": "annualIncome", "type": "number"},
        {"provider": "REVENUE-DEPARTMENT", "service": "REV-MAHA-101", "field": "state", "canonical": "domicileState", "type": "string"},
        {"provider": "REVENUE-DEPARTMENT", "service": "REV-MAHA-101", "field": "recordId", "canonical": "certificateReference", "type": "string"},
        {"provider": "SOCIAL-WELFARE-DEPARTMENT", "service": "SW-CASTE-301", "field": "caste", "canonical": "casteCategory", "type": "string"},
        {"provider": "EDUCATION-DEPARTMENT", "service": "EDU-ACA-201", "field": "studentId", "canonical": "academicRecordReference", "type": "string"},
        {"provider": "AUTHORIZED-DBT", "service": "DBT-BANK-401", "field": "accountStatus", "canonical": "bankLinkageStatus", "type": "string"},
    ]
    with Session(engine) as session:
        for mapping in mappings:
            provider_id = mapping["provider"]
            if session.get(ProviderRow, provider_id) is None:
                continue
            mapping_id = f"{provider_id}:{mapping['field']}"
            if session.get(SchemaMappingRow, mapping_id) is not None:
                continue
            session.add(SchemaMappingRow(
                mapping_id=mapping_id,
                provider_id=provider_id,
                service_id=mapping["service"] if session.get(ServiceCatalogRow, mapping["service"]) is not None else None,
                department_field=mapping["field"],
                canonical_field=mapping["canonical"],
                data_type=mapping.get("type", "string"),
                payload=mapping,
            ))
        session.commit()


def citizens_seeded() -> bool:
    with Session(engine) as session:
        return session.query(CitizenRow).count() > 0


def seed_platform_citizens() -> None:
    """Bootstrap the synthetic platform citizen pool used across department sandboxes."""
    if os.getenv("SANGAM_SEED_SYNTHETIC_DATA", "false").lower() not in {"1", "true", "yes"}:
        return
    with Session(engine) as session:
        if session.query(CitizenRow).count() > 0:
            return
        from app.seeds.synthetic_identity_pool import generate_citizen_pool
        now = datetime.now(timezone.utc)
        for citizen in generate_citizen_pool():
            session.add(CitizenRow(
                citizen_id=citizen["citizenId"],
                full_name=citizen["name"],
                date_of_birth=citizen["dob"],
                gender=citizen.get("gender"),
                phone=citizen.get("phone"),
                district=citizen.get("district"),
                persona=citizen.get("persona"),
                is_synthetic=True,
                created_at=now,
                updated_at=now,
                payload=citizen,
            ))
        session.commit()


DEPARTMENT_SANDBOX_PROVIDERS = [
    {"departmentId": "REVENUE-SANDBOX", "departmentName": "Revenue Sandbox", "providerId": "REVENUE-SANDBOX-LAND", "providerName": "Revenue Sandbox API - Land Records", "requirementCode": "LAND_HOLDING", "serviceId": "REV-SANDBOX-LAND-001", "serviceName": "Land Record Lookup", "httpPath": "/departments/revenue/land-records/{citizenRef}", "mapping": ("survey_number", "landSurveyNumber")},
    {"departmentId": "EDUCATION-SANDBOX", "departmentName": "Education Sandbox", "providerId": "EDUCATION-SANDBOX-SCHOLARSHIP", "providerName": "Education Sandbox API - Scholarship Eligibility", "requirementCode": "SCHOLARSHIP_ELIGIBILITY", "serviceId": "EDU-SANDBOX-SCHOLARSHIP-001", "serviceName": "Scholarship Eligibility Lookup", "httpPath": "/departments/education/scholarship-eligibility/{citizenRef}", "mapping": ("eligible", "scholarshipEligible")},
    {"departmentId": "SOCIAL-WELFARE-SANDBOX", "departmentName": "Social Welfare Sandbox", "providerId": "SOCIAL-WELFARE-SANDBOX-ENROLLMENT", "providerName": "Social Welfare Sandbox API - Scheme Enrollment", "requirementCode": "SCHEME_ENROLLMENT_STATUS", "serviceId": "SW-SANDBOX-ENROLL-001", "serviceName": "Scheme Enrollment Lookup", "httpPath": "/departments/social-welfare/scheme-enrollments/{citizenRef}", "mapping": ("scheme_name", "welfareSchemeName")},
    {"departmentId": "AGRICULTURE-SANDBOX", "departmentName": "Agriculture Sandbox", "providerId": "AGRICULTURE-SANDBOX-FARMER", "providerName": "Agriculture Sandbox API - Farmer Registration", "requirementCode": "FARMER_REGISTRATION", "serviceId": "AGR-SANDBOX-FARMER-001", "serviceName": "Farmer Registration Lookup", "httpPath": "/departments/agriculture/farmers/{citizenRef}", "mapping": ("farmer_name", "name")},
    {"departmentId": "AGRICULTURE-SANDBOX", "departmentName": "Agriculture Sandbox", "providerId": "AGRICULTURE-SANDBOX-LOAN", "providerName": "Agriculture Sandbox API - Crop Loan Status", "requirementCode": "CROP_LOAN_STATUS", "serviceId": "AGR-SANDBOX-LOAN-001", "serviceName": "Crop Loan Status Lookup", "httpPath": "/departments/agriculture/crop-loans/{citizenRef}", "mapping": ("loan_amount", "cropLoanAmount")},
    {"departmentId": "TRANSPORT-SANDBOX", "departmentName": "Transport Sandbox", "providerId": "TRANSPORT-SANDBOX-VEHICLE", "providerName": "Transport Sandbox API - Vehicle Registration", "requirementCode": "VEHICLE_REGISTRATION", "serviceId": "TRN-SANDBOX-VEHICLE-001", "serviceName": "Vehicle Registration Lookup", "httpPath": "/departments/transport/vehicle-registrations/{citizenRef}", "authType": "API_KEY", "mapping": ("vehicle_number", "vehicleRegistrationNumber")},
    {"departmentId": "TRANSPORT-SANDBOX", "departmentName": "Transport Sandbox", "providerId": "TRANSPORT-SANDBOX-LICENCE", "providerName": "Transport Sandbox API - Driving Licence", "requirementCode": "DRIVING_LICENCE", "serviceId": "TRN-SANDBOX-LICENCE-001", "serviceName": "Driving Licence Lookup", "httpPath": "/departments/transport/driving-licences/{citizenRef}", "authType": "API_KEY", "mapping": ("licence_class", "drivingLicenceClass")},
    {"departmentId": "LABOUR-SANDBOX", "departmentName": "Labour Sandbox", "providerId": "LABOUR-SANDBOX-WORKER", "providerName": "Labour Sandbox API - Worker Registration", "requirementCode": "WORKER_REGISTRATION", "serviceId": "LAB-SANDBOX-WORKER-001", "serviceName": "Worker Registration Lookup", "httpPath": "/departments/labour/workers/{citizenRef}", "mapping": ("occupation", "workerOccupation")},
    {"departmentId": "LABOUR-SANDBOX", "departmentName": "Labour Sandbox", "providerId": "LABOUR-SANDBOX-WELFARE", "providerName": "Labour Sandbox API - Welfare Board Membership", "requirementCode": "WELFARE_BOARD_MEMBERSHIP", "serviceId": "LAB-SANDBOX-WELFARE-001", "serviceName": "Welfare Board Membership Lookup", "httpPath": "/departments/labour/welfare-board-memberships/{citizenRef}", "mapping": ("membership_number", "welfareBoardMembershipNumber")},
    {"departmentId": "FOOD-CIVIL-SUPPLIES-SANDBOX", "departmentName": "Food & Civil Supplies Sandbox", "providerId": "FOOD-CIVIL-SUPPLIES-SANDBOX-RATION", "providerName": "Food Civil Supplies Sandbox API - Ration Card", "requirementCode": "RATION_CARD", "serviceId": "FCS-SANDBOX-RATION-001", "serviceName": "Ration Card Lookup", "httpPath": "/departments/food-civil-supplies/ration-cards/{citizenRef}", "mapping": ("card_category", "rationCardCategory")},
    {"departmentId": "HOUSING-SANDBOX", "departmentName": "Housing Sandbox", "providerId": "HOUSING-SANDBOX-ALLOTMENT", "providerName": "Housing Sandbox API - Allotment Status", "requirementCode": "HOUSING_ALLOTMENT", "serviceId": "HSG-SANDBOX-ALLOTMENT-001", "serviceName": "Housing Allotment Lookup", "httpPath": "/departments/housing/allotments/{citizenRef}", "mapping": ("unit_number", "housingUnitNumber")},
    {"departmentId": "SKILL-EMPLOYMENT-SANDBOX", "departmentName": "Skill Development & Employment Sandbox", "providerId": "SKILL-EMPLOYMENT-SANDBOX-SKILL", "providerName": "Skill Employment Sandbox API - Skill Certification", "requirementCode": "SKILL_CERTIFICATION", "serviceId": "SKE-SANDBOX-SKILL-001", "serviceName": "Skill Certification Lookup", "httpPath": "/departments/skill-employment/skill-certifications/{citizenRef}", "mapping": ("trade", "certifiedTrade")},
    {"departmentId": "SKILL-EMPLOYMENT-SANDBOX", "departmentName": "Skill Development & Employment Sandbox", "providerId": "SKILL-EMPLOYMENT-SANDBOX-EMPLOYMENT", "providerName": "Skill Employment Sandbox API - Employment Registration", "requirementCode": "EMPLOYMENT_REGISTRATION", "serviceId": "SKE-SANDBOX-EMPLOYMENT-001", "serviceName": "Employment Registration Lookup", "httpPath": "/departments/skill-employment/employment-registrations/{citizenRef}", "mapping": ("exchange_office", "employmentExchangeOffice")},
    {"departmentId": "MUNICIPAL-HEALTH-SANDBOX", "departmentName": "Municipal Health Sandbox", "providerId": "MUNICIPAL-HEALTH-SANDBOX-BIRTH", "providerName": "Municipal Health Sandbox API - Birth Certificate", "requirementCode": "BIRTH_CERTIFICATE", "serviceId": "MUN-SANDBOX-BIRTH-001", "serviceName": "Birth Certificate Lookup", "httpPath": "/departments/municipal-health/birth-certificates/{citizenRef}", "mapping": ("registration_number", "birthRegistrationNumber")},
    {"departmentId": "MUNICIPAL-HEALTH-SANDBOX", "departmentName": "Municipal Health Sandbox", "providerId": "MUNICIPAL-HEALTH-SANDBOX-IMMUNIZATION", "providerName": "Municipal Health Sandbox API - Immunization Record", "requirementCode": "IMMUNIZATION_RECORD", "serviceId": "MUN-SANDBOX-IMMUNIZATION-001", "serviceName": "Immunization Record Lookup", "httpPath": "/departments/municipal-health/immunization-records/{citizenRef}", "mapping": ("dob", "dateOfBirth")},
]


def department_sandbox_providers_seeded() -> bool:
    with Session(engine) as session:
        return session.query(ProviderRow).filter(ProviderRow.provider_id.in_([item["providerId"] for item in DEPARTMENT_SANDBOX_PROVIDERS])).count() > 0


def seed_department_sandbox_providers() -> None:
    """Register the 10 department sandboxes as PostgreSQL-owned providers.

    Additive only: distinct department/provider/service ids from the existing
    4 in-process demo providers, no scheme currently lists these requirement
    codes, so this cannot change existing dependency selection or workflows.
    Each provider uses the new "Department Sandbox API" adapter, which always
    calls that department's REST API over HTTP (see app.department_api) --
    never the sandbox database directly.
    """
    if os.getenv("SANGAM_SEED_DEPARTMENT_PROVIDERS", "false").lower() not in {"1", "true", "yes"}:
        return
    with Session(engine) as session:
        for entry in DEPARTMENT_SANDBOX_PROVIDERS:
            if session.get(DepartmentRow, entry["departmentId"]) is None:
                session.add(DepartmentRow(department_id=entry["departmentId"], name=entry["departmentName"], payload={"departmentId": entry["departmentId"], "name": entry["departmentName"], "simulated": True}))
        session.flush()
        for entry in DEPARTMENT_SANDBOX_PROVIDERS:
            provider_id = entry["providerId"]
            if session.get(ProviderRow, provider_id) is None:
                session.add(ProviderRow(
                    provider_id=provider_id, department_id=entry["departmentId"], name=entry["providerName"],
                    adapter_type="Department Sandbox API", contract_version="v1", environment="SANDBOX",
                    auth_type=entry.get("authType", "NONE"), endpoint_ref="DEPARTMENT_API_BASE_URL",
                    timeout_seconds=5, max_attempts=3,
                    payload={"providerId": provider_id, "name": entry["providerName"], "httpPath": entry["httpPath"], "simulated": True},
                ))
            if session.get(ServiceCatalogRow, entry["serviceId"]) is None:
                session.add(ServiceCatalogRow(service_id=entry["serviceId"], provider_id=provider_id, name=entry["serviceName"], requirement_code=entry["requirementCode"], payload={"serviceId": entry["serviceId"], "requirementCode": entry["requirementCode"], "requiredService": entry["serviceName"]}))
            capability_id = f"{provider_id}:{entry['requirementCode']}"
            if session.get(ProviderCapabilityRow, capability_id) is None:
                session.add(ProviderCapabilityRow(capability_id=capability_id, provider_id=provider_id, capability_code=entry["requirementCode"], service_id=entry["serviceId"], payload={"capabilityId": capability_id, "capabilityCode": entry["requirementCode"], "providerId": provider_id, "serviceId": entry["serviceId"]}))
        session.commit()
    from app.core.redis_service import RedisService
    RedisService().delete("sangam:cache:catalog:v1")


def seed_department_sandbox_schema_mappings() -> None:
    """Seed one demonstrative department-field -> canonical-field mapping per
    new sandbox provider. Gated with the sandbox providers themselves since a
    mapping is meaningless without its provider."""
    if os.getenv("SANGAM_SEED_DEPARTMENT_PROVIDERS", "false").lower() not in {"1", "true", "yes"}:
        return
    with Session(engine) as session:
        for entry in DEPARTMENT_SANDBOX_PROVIDERS:
            provider_id = entry["providerId"]
            if session.get(ProviderRow, provider_id) is None:
                continue
            department_field, canonical_field = entry["mapping"]
            mapping_id = f"{provider_id}:{department_field}"
            if session.get(SchemaMappingRow, mapping_id) is not None:
                continue
            session.add(SchemaMappingRow(
                mapping_id=mapping_id, provider_id=provider_id, service_id=entry["serviceId"],
                department_field=department_field, canonical_field=canonical_field, data_type="string",
                payload={"provider": provider_id, "departmentField": department_field, "canonicalField": canonical_field},
            ))
        session.commit()


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


def provider_capability_snapshot(requirement_code: str | None = None) -> list[dict]:
    """Return enabled provider capabilities joined to active provider/services.

    This is the authoritative dependency-selection projection. Service payloads
    may provide display metadata, but cannot authorize a provider by themselves.
    Database errors intentionally propagate so callers can fail closed.
    """
    with Session(engine) as session:
        query = (
            session.query(ProviderCapabilityRow, ProviderRow, ServiceCatalogRow)
            .join(ProviderRow, ProviderRow.provider_id == ProviderCapabilityRow.provider_id)
            .join(ServiceCatalogRow, ServiceCatalogRow.service_id == ProviderCapabilityRow.service_id)
            .filter(ProviderCapabilityRow.enabled.is_(True), ProviderRow.active.is_(True), ServiceCatalogRow.active.is_(True))
        )
        if requirement_code:
            query = query.filter(ProviderCapabilityRow.capability_code == requirement_code)
        definitions = []
        for capability, provider, service in query.all():
            capability_metadata = capability.payload or {}
            service_metadata = service.payload or {}
            definitions.append({
                "capabilityId": capability.capability_id,
                "requirementCode": capability.capability_code,
                "requirementType": capability_metadata.get("requirementType", capability.capability_code),
                "requiredService": service.name,
                "serviceName": service.name,
                "serviceId": service.service_id,
                "provider": provider.name,
                "providerId": provider.provider_id,
                "adapter": provider.adapter_type,
                "adapterType": provider.adapter_type,
                "environment": provider.environment,
                "priority": capability_metadata.get("priority", service_metadata.get("priority", 100)),
                "timeoutSeconds": provider.timeout_seconds,
                "maxAttempts": provider.max_attempts,
                "sandboxHandler": service_metadata.get("sandboxHandler"),
                "reason": "Enabled provider capability",
            })
        return definitions


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
                "departmentMr": metadata.get("departmentMr"),
                "description": metadata.get("description", "Configured government service"),
                "category": metadata.get("category", "Government services"),
                "benefits": metadata.get("benefits"),
                "eligibility": metadata.get("eligibility"),
                "applicationWindow": metadata.get("applicationWindow"),
                "synthetic": metadata.get("synthetic", False),
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
        # The legacy snapshot is destructive, so serialize it against every
        # application row it can replace.  These are row locks, not a table
        # lock; repository writers either finish before this snapshot or wait
        # until it commits and then see the resulting row.
        application_rows = session.execute(select(ApplicationRow).with_for_update()).scalars().all()
        protected_app_ids = {row.app_id for row in application_rows if row.authoritative_at is not None}

        def delete_unprotected(model, column):
            if not protected_app_ids:
                session.execute(delete(model))
                return
            session.execute(delete(model).where(~column.in_(protected_app_ids)))

        delete_unprotected(WorkflowHistoryRow, WorkflowHistoryRow.app_id)
        delete_unprotected(DependencyRow, DependencyRow.app_id)
        delete_unprotected(EntityReviewRow, EntityReviewRow.app_id)
        delete_unprotected(ConflictReviewRow, ConflictReviewRow.app_id)
        for model, column in ((NotificationRow, NotificationRow.app_id),):
            if not protected_app_ids:
                session.execute(delete(model))
            else:
                session.execute(delete(model).where(or_(column.is_(None), ~column.in_(protected_app_ids))))
        if not protected_app_ids:
            session.execute(delete(EventRow))
            session.execute(delete(AuditEntryRow))
        else:
            session.execute(delete(EventRow).where(or_(EventRow.app_id.is_(None), ~EventRow.app_id.in_(protected_app_ids))))
            # correlation_id is the existing application-scoped audit
            # convention.  Uncorrelated audit entries remain legacy state;
            # no JSONB inference is used here.
            session.execute(delete(AuditEntryRow).where(or_(AuditEntryRow.correlation_id.is_(None), ~AuditEntryRow.correlation_id.in_(protected_app_ids))))
        session.execute(delete(ApplicationRow).where(ApplicationRow.authoritative_at.is_(None)))
        for model in (SessionRow, IntegrationStateRow, MockStateRow):
            session.execute(delete(model))
        for app_id, app in workflow_engine.APPLICATIONS.items():
            if app_id in protected_app_ids:
                continue
            session.add(ApplicationRow(app_id=app_id, citizen_id=app["citizenId"], status=app["status"], payload=app))
            for history in app.get("statusHistory", []):
                session.add(WorkflowHistoryRow(app_id=app_id, status=history["status"], occurred_at=history["at"], payload=history))
        for dep_id, dependency in workflow_engine.DEPENDENCIES.items():
            if dependency["appId"] in protected_app_ids:
                continue
            session.add(DependencyRow(dependency_id=dep_id, app_id=dependency["appId"], status=dependency["status"], payload=dependency))
        consent_version_updates = []
        # Keep the legacy citizen-keyed view compatible with direct callers,
        # while persisting every consent independently by consent ID.
        for citizen_id, receipt in consent_manager.CONSENTS.items():
            consent_id = receipt.get("consentId") if isinstance(receipt, dict) else None
            if consent_id:
                consent_manager.CONSENTS_BY_ID[consent_id] = receipt
        for consent_id, receipt in consent_manager.CONSENTS_BY_ID.items():
            citizen_id = receipt["citizenId"]
            app = next((candidate for candidate in workflow_engine.APPLICATIONS.values() if candidate.get("consentId") == receipt.get("consentId")), None) or workflow_engine.find_active_application(citizen_id)
            if app and app["appId"] in protected_app_ids:
                continue
            source_version = receipt.get("_source_version")
            if not isinstance(source_version, int) or isinstance(source_version, bool):
                continue
            row = session.execute(
                select(ConsentRow).where(ConsentRow.consent_id == receipt["consentId"]).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                continue
            payload = {key: value for key, value in receipt.items() if key != "_source_version"}
            expected_app_id = app["appId"] if app else None
            if row.payload == payload and row.citizen_id == citizen_id and row.app_id == expected_app_id:
                consent_version_updates.append((receipt, row.version))
                continue
            if row.version != source_version:
                raise ConsentConcurrencyError(f"Consent {receipt['consentId']} has version {row.version}, expected {source_version}")
            row.citizen_id = citizen_id
            row.app_id = expected_app_id
            row.payload = payload
            row.version = source_version + 1
            consent_version_updates.append((receipt, row.version))
        for review_id, review in workflow_engine.ENTITY_REVIEWS.items():
            if review["appId"] in protected_app_ids:
                continue
            session.add(EntityReviewRow(review_id=review_id, app_id=review["appId"], payload=review))
        for review_id, review in workflow_engine.CONFLICT_REVIEWS.items():
            if review["appId"] in protected_app_ids:
                continue
            session.add(ConflictReviewRow(review_id=review_id, app_id=review["appId"], payload=review))
        for item in notification_manager.notifications:
            if item.get("applicationId") in protected_app_ids:
                continue
            session.add(NotificationRow(notification_id=item["notificationId"], recipient_user_id=item["recipientUserId"], app_id=item.get("applicationId"), payload=item))
        for event in event_bus.events:
            payload = event.get("payload", {})
            if payload.get("appId") in protected_app_ids:
                continue
            session.add(EventRow(app_id=payload.get("appId"), event_type=event["type"], occurred_at=event["timestamp"], payload=event))
        for entry in audit_bus.entries:
            if entry.get("correlationId") in protected_app_ids:
                continue
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
        from sqlalchemy.dialects.postgresql import insert as postgres_insert
        for key, value in counters.items():
            if key == "application":
                session.execute(
                    postgres_insert(CounterRow)
                    .values(counter_key=key, next_value=value)
                    .on_conflict_do_update(
                        index_elements=[CounterRow.counter_key],
                        set_={"next_value": func.greatest(CounterRow.next_value, value)},
                    )
                )
            else:
                counter = session.get(CounterRow, key)
                if counter is None:
                    session.add(CounterRow(counter_key=key, next_value=value))
                else:
                    counter.next_value = value
        session.commit()
        for receipt, version in consent_version_updates:
            receipt["_source_version"] = version
            consent_manager.CONSENT_SOURCE_VERSIONS[receipt["consentId"]] = version


def persist_transition(app: dict, history_entry: dict) -> None:
    """Atomically store the current application snapshot and its new history row."""
    with Session(engine) as session:
        try:
            row = session.execute(
                select(ApplicationRow).where(ApplicationRow.app_id == app["appId"]).with_for_update()
            ).scalar_one_or_none()
            if row is not None and row.authoritative_at is not None:
                raise ApplicationAuthorityError("Application changed concurrently; please reload and retry.")
            if row is None:
                session.add(ApplicationRow(app_id=app["appId"], citizen_id=app["citizenId"], status=app["status"], payload=app))
            else:
                row.citizen_id = app["citizenId"]
                row.status = app["status"]
                row.payload = app
            session.add(WorkflowHistoryRow(app_id=app["appId"], status=history_entry["status"], occurred_at=history_entry["at"], payload=history_entry))
            session.commit()
        except Exception:
            session.rollback()
            raise


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
        consent_manager.CONSENTS_BY_ID.clear()
        consent_manager.CONSENT_SOURCE_VERSIONS.clear()
        for row in session.query(ConsentRow).order_by(ConsentRow.consent_id).all():
            consent_manager.CONSENT_SOURCE_VERSIONS[row.consent_id] = row.version
            receipt = dict(row.payload or {})
            receipt["_source_version"] = row.version
            consent_manager.CONSENTS_BY_ID[row.consent_id] = receipt
        by_citizen = {}
        for receipt in consent_manager.CONSENTS_BY_ID.values():
            citizen_id = receipt.get("citizenId")
            if citizen_id in by_citizen:
                by_citizen[citizen_id] = None
            elif citizen_id:
                by_citizen[citizen_id] = receipt
        for citizen_id, receipt in by_citizen.items():
            if receipt is not None:
                consent_manager.CONSENTS[citizen_id] = receipt
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
