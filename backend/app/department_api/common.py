"""Shared framework pieces reused by every department router.

Session handling, the response envelope shape, the synthetic-data
disclaimer, correlation-id propagation, and API-key auth are implemented once
here. Each department router only supplies its own domain queries and field
names -- this is the "reusable API service pattern" instead of duplicating an
application per department.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

SYNTHETIC_DISCLAIMER = (
    "SYNTHETIC/DEMO DATA. This is a simulated department system built for the "
    "SANGAM prototype. It is not connected to, and does not represent, any "
    "live Maharashtra Government system."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def correlation_id_header(x_correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID")) -> Optional[str]:
    return x_correlation_id


def session_dependency(engine):
    """Build a FastAPI dependency yielding a session bound to one department's
    own engine. Each department keeps its own engine; nothing here ever spans
    two departments' databases in one session."""
    def _get_session():
        session = Session(engine, future=True)
        try:
            yield session
        finally:
            session.close()
    return _get_session


def require_api_key(department_env_key: str):
    """Build an auth dependency for a department whose provider is configured
    with API_KEY auth. Reads ``DEPARTMENT_API_KEY_<department_env_key>``; if
    that env var is unset, the department has no key configured and the
    dependency allows every request through (matches the SANGAM-side
    convention where auth_type=NONE means no credential is required)."""
    env_var = f"DEPARTMENT_API_KEY_{department_env_key.upper()}"

    def _check(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        expected = os.getenv(env_var)
        if expected and x_api_key != expected:
            raise HTTPException(status_code=401, detail={"status": "UNAUTHORIZED", "synthetic": True, "disclaimer": SYNTHETIC_DISCLAIMER})
    return _check


def envelope(data: dict, *, source_system: str, correlation_id: Optional[str], record_id: str, status: Optional[str] = None) -> dict:
    body = {
        "id": record_id,
        "sourceSystem": source_system,
        "synthetic": True,
        "disclaimer": SYNTHETIC_DISCLAIMER,
        "correlationId": correlation_id,
        "retrievedAt": now_iso(),
        "data": data,
    }
    if status is not None:
        body["status"] = status
    return body


def not_found(source_system: str, correlation_id: Optional[str]) -> JSONResponse:
    return JSONResponse(status_code=404, content={
        "sourceSystem": source_system,
        "synthetic": True,
        "disclaimer": SYNTHETIC_DISCLAIMER,
        "correlationId": correlation_id,
        "retrievedAt": now_iso(),
        "status": "NOT_FOUND",
        "data": None,
    })


def department_health(engine, source_system: str):
    """Health of one department system: the API is up *and* can reach its
    own database. 503 when the database is unreachable, so callers (SANGAM's
    provider health checks) see the department as unavailable."""
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "CONNECTED"
    except Exception:
        database = "UNAVAILABLE"
    body = {"status": "AVAILABLE" if database == "CONNECTED" else "UNAVAILABLE", "database": database,
            "sourceSystem": source_system, "synthetic": True}
    return body if database == "CONNECTED" else JSONResponse(status_code=503, content=body)
