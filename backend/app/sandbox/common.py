"""Reusable infrastructure shared by every department sandbox.

Each department module defines its own ``DeclarativeBase`` subclass (so its
tables live in their own SQLAlchemy metadata / their own physical database)
and its own domain models, but all of them use these same helpers for engine
creation, timestamp/synthetic-flag columns, a generic synthetic-document
table, and deterministic case selection for seed data. This is what keeps
"add a department" a data/schema exercise per department rather than a
reimplementation of connection handling, seeding plumbing, etc.
"""
from __future__ import annotations

import os
import random
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

SANDBOX_DATA_DIR = Path(os.getenv("SANDBOX_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "sandboxes"))

CASE_WEIGHTS = {"POSITIVE": 0.55, "PENDING": 0.2, "MISSING": 0.15, "FAILURE": 0.10}


def sandbox_db_url(department_key: str) -> str:
    """Resolve this department's own database URL.

    Defaults to an isolated SQLite file so every department sandbox works out
    of the box with zero extra infrastructure. Setting
    ``SANDBOX_DB_URL_<DEPARTMENT_KEY>`` (e.g. ``SANDBOX_DB_URL_REVENUE``)
    points the same department at a separate PostgreSQL database instead --
    the department's tables/queries do not change either way.
    """
    env_key = f"SANDBOX_DB_URL_{department_key.upper()}"
    configured = os.getenv(env_key)
    if configured:
        return configured
    SANDBOX_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(SANDBOX_DATA_DIR / f'{department_key}.db').as_posix()}"


def make_engine(department_key: str):
    url = sandbox_db_url(department_key)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite:///") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def session_scope(engine):
    session = Session(engine, future=True)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class TimestampMixin:
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SyntheticFlagMixin:
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


def build_document_table(base, table_name: str = "synthetic_documents"):
    """Return a ``SyntheticDocument`` model bound to a department's own Base.

    A lightweight, clearly-labeled synthetic document: enough metadata + a
    generated text body to demonstrate document-backed requirements without
    depending on a heavyweight PDF toolchain that is out of scope here.
    """
    class SyntheticDocument(base, TimestampMixin, SyntheticFlagMixin):
        __tablename__ = table_name
        document_id: Mapped[str] = mapped_column(String(160), primary_key=True)
        owner_reference: Mapped[str] = mapped_column(String(160), index=True)
        title: Mapped[str] = mapped_column(String(200))
        content_type: Mapped[str] = mapped_column(String(60), default="text/plain")
        content_text: Mapped[str] = mapped_column(Text)
        issued_on: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    return SyntheticDocument


def render_synthetic_document(title: str, citizen_name: str, department_label: str, fields: dict) -> str:
    """Generate a small, human-readable synthetic document body."""
    lines = [
        f"*** SYNTHETIC / DEMO DOCUMENT -- {department_label} ***",
        "This record is generated demo data. It does not represent a real government document.",
        "",
        title,
        f"Name: {citizen_name}",
    ]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def case_bucket(rng: random.Random, weights: dict | None = None) -> str:
    """Pick POSITIVE / PENDING / MISSING / FAILURE for one synthetic record."""
    weights = weights or CASE_WEIGHTS
    labels = list(weights.keys())
    return rng.choices(labels, weights=[weights[label] for label in labels])[0]


def record_id(department_key: str, sequence: int, prefix: str = "REC") -> str:
    return f"{department_key.upper()}-{prefix}-{sequence:05d}"
