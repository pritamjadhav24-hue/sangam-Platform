"""Shared reference-data fixtures for tests that run against the shared
PostgreSQL development database.

Tests need the requirement vocabulary seeded, but the running demo depends
on it too -- so a test must only ever remove what it added itself, and a test
that needs a genuinely empty table must put the original rows back.
"""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.core.persistence import RequirementCatalogRow, engine, seed_requirement_catalog


def seed_test_vocabulary() -> set[str]:
    """Seed the canonical requirement vocabulary; return only the codes this
    call actually inserted (empty when the demo vocabulary already exists)."""
    with Session(engine) as session:
        existing = {row.requirement_code for row in session.query(RequirementCatalogRow)}
    with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
        seed_requirement_catalog()
    with Session(engine) as session:
        return {row.requirement_code for row in session.query(RequirementCatalogRow)} - existing


def remove_test_vocabulary(codes: set[str]) -> None:
    if not codes:
        return
    with Session(engine) as session:
        session.query(RequirementCatalogRow).filter(RequirementCatalogRow.requirement_code.in_(codes)).delete(synchronize_session=False)
        session.commit()


def snapshot_tables(*models) -> list[tuple]:
    """Capture every row of the given tables (pass parents before children,
    e.g. departments, providers, services, capabilities, mappings)."""
    with Session(engine) as session:
        return [(model, [dict(row) for row in session.execute(select(model.__table__)).mappings()]) for model in models]


def _key(model, row) -> tuple:
    return tuple(row[column.name] for column in model.__table__.primary_key.columns)


def restore_tables(snapshot: list[tuple], reinsert: bool = True) -> None:
    """Bring the tables back to the snapshot by primary key: rows added since
    are deleted (children first), rows removed since are re-inserted
    (parents first) and rows changed in place are updated back -- unless
    ``reinsert`` is False, which only removes added rows. Rows present in
    both are never deleted and re-created, so nothing a foreign key points
    at is disturbed."""
    with Session(engine) as session:
        for model, rows in reversed(snapshot):
            keep = {_key(model, row) for row in rows}
            current = session.execute(select(model.__table__)).mappings().all()
            for row in current:
                if _key(model, row) not in keep:
                    columns = model.__table__.primary_key.columns
                    session.execute(delete(model.__table__).where(*[column == row[column.name] for column in columns]))
        for model, rows in snapshot if reinsert else ():
            present = {_key(model, row): dict(row) for row in session.execute(select(model.__table__)).mappings()}
            missing = [row for row in rows if _key(model, row) not in present]
            if missing:
                session.execute(insert(model.__table__), missing)
            columns = model.__table__.primary_key.columns
            for row in rows:
                current = present.get(_key(model, row))
                if current is not None and current != row:
                    # Modified in place by the test (e.g. a capability disabled): put it back.
                    session.execute(update(model.__table__).where(*[column == row[column.name] for column in columns]).values(**row))
        session.commit()


def guard_module_runtime_state(module_globals: dict) -> None:
    """Wrap a test module's setUpModule/tearDownModule so every runtime row
    it leaves behind -- applications, consents, documents, citizen
    notifications, provider jobs/incidents, worker heartbeats -- is removed
    when the module finishes. Rows that existed before the module ran are
    never touched. Call once at the bottom of the test module."""
    from app.core.persistence import (
        ApplicationRow, CitizenNotificationRow, ConsentRow, DocumentRow, ProviderIncidentRow, ProviderJobRow, WorkerHeartbeatRow,
    )
    tables = (ApplicationRow, ConsentRow, DocumentRow, CitizenNotificationRow, ProviderJobRow, ProviderIncidentRow, WorkerHeartbeatRow)
    original_setup = module_globals.get("setUpModule")
    original_teardown = module_globals.get("tearDownModule")
    snapshot: list = []

    def setUpModule():
        snapshot[:] = snapshot_tables(*tables)
        if original_setup:
            original_setup()

    def tearDownModule():
        try:
            if original_teardown:
                original_teardown()
        finally:
            restore_tables(snapshot, reinsert=False)

    module_globals["setUpModule"] = setUpModule
    module_globals["tearDownModule"] = tearDownModule


def snapshot_provider_catalog() -> list[tuple]:
    """The provider registry + vocabulary tables a department-API test seeds
    into and cleans up afterwards."""
    from app.core.persistence import DepartmentRow, ProviderCapabilityRow, ProviderRow, SchemaMappingRow, ServiceCatalogRow
    return snapshot_tables(DepartmentRow, ProviderRow, ServiceCatalogRow, ProviderCapabilityRow, SchemaMappingRow, RequirementCatalogRow)


def non_demo_citizens(session):
    """Synthetic citizens tests may borrow and clean up freely: the pool minus
    the persona accounts the demo citizen switcher signs in as, so running
    the suite never touches a presenter's demo applications."""
    from app.core.persistence import CitizenRow, select_demo_switchable_citizen_ids
    return (session.query(CitizenRow)
            .filter(CitizenRow.citizen_id.notin_(select_demo_switchable_citizen_ids()))
            .order_by(CitizenRow.citizen_id))
