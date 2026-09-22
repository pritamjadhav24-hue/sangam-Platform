"""Applies PostgreSQL-owned department-field -> canonical-field mappings.

This is the runtime use of the ``schema_mappings`` table (see
``app.core.persistence.SchemaMappingRow``): given a provider's raw response
fields (in that department's own naming convention), translate the fields
that have a registered mapping into SANGAM's canonical representation.
Unmapped fields are left out of the canonical view -- they remain available
in the adapter's ``raw`` field for anything that still needs them.
"""
from __future__ import annotations


def apply_schema_mapping(provider_id: str, department_fields: dict) -> dict:
    if not provider_id or not isinstance(department_fields, dict):
        return {}
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.core.persistence import SchemaMappingRow, engine

    with Session(engine) as session:
        mappings = session.execute(
            select(SchemaMappingRow.department_field, SchemaMappingRow.canonical_field)
            .where(SchemaMappingRow.provider_id == provider_id, SchemaMappingRow.active.is_(True))
        ).all()
    canonical: dict = {}
    for department_field, canonical_field in mappings:
        if department_field in department_fields:
            canonical[canonical_field] = department_fields[department_field]
    return canonical
