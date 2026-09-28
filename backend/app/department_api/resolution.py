"""Canonical record lookup: the one contract every department API offers SANGAM.

    POST /departments/<department>/resolve/<record-type>
    {"citizenRef": ..., "name": ..., "dob": ..., "phone": ..., "address": ...,
     "identifiers": {"<department identifier>": ...}}

The department -- not SANGAM -- decides who the person is in its own records:

1. a department identifier it issued itself (student id, beneficiary id, ...);
2. the SANGAM cross-reference it holds for the person, if any;
3. otherwise its own demographic lookup: same date of birth *and* the same
   name or phone. Exactly one person must qualify -- an ambiguous lookup
   answers "no record" rather than guessing.

It then serves the requested record through the same query its existing GET
endpoint uses, and says how the person was found (``match``). SANGAM never
sees table names or queries this database; it re-checks the returned identity
with its own entity resolution before using anything.

Deliberately self-contained (no SANGAM imports): a department system owns its
own matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.department_api.common import SYNTHETIC_DISCLAIMER, correlation_id_header, not_found, now_iso


class CanonicalLookup(BaseModel):
    citizenRef: Optional[str] = None
    name: Optional[str] = None
    dob: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    identifiers: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class PersonIndex:
    """Where a department keeps the people its records belong to."""
    model: type
    id_field: str
    name_field: str
    dob_field: str
    phone_field: Optional[str] = None
    ref_field: str = "citizen_ref"
    # Identifier names SANGAM may send (``identifiers``) that map to id_field.
    identifier_names: tuple[str, ...] = field(default_factory=tuple)


def _name_tokens(value) -> frozenset:
    words = re.sub(r"[^a-z ]", " ", str(value or "").lower()).split()
    return frozenset(word for word in words if len(word) > 1)  # initials ("S.") are not evidence


def _phone(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""


def _dob_variants(value) -> list[str]:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            day = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return sorted({day.isoformat(), day.strftime("%d-%m-%Y"), day.strftime("%d/%m/%Y"), day.strftime("%Y/%m/%d")})
    return []


def find_person(session, index: PersonIndex, lookup: CanonicalLookup):
    """(person, method) or (None, reason)."""
    for name in index.identifier_names:
        value = (lookup.identifiers or {}).get(name)
        if value:
            person = session.get(index.model, value)
            if person is not None:
                return person, "DEPARTMENT_IDENTIFIER"
    if lookup.citizenRef:
        person = session.query(index.model).filter(getattr(index.model, index.ref_field) == lookup.citizenRef).first()
        if person is not None:
            return person, "CROSS_REFERENCE"
    variants = _dob_variants(lookup.dob)
    wanted_name, wanted_phone = _name_tokens(lookup.name), _phone(lookup.phone)
    if not variants or not (wanted_name or wanted_phone):
        return None, "INSUFFICIENT_IDENTITY"
    candidates = session.query(index.model).filter(getattr(index.model, index.dob_field).in_(variants)).all()
    matches = {}
    for person in candidates:
        same_name = bool(wanted_name) and _name_tokens(getattr(person, index.name_field)) == wanted_name
        same_phone = bool(wanted_phone) and index.phone_field and _phone(getattr(person, index.phone_field)) == wanted_phone
        if same_name or same_phone:
            matches.setdefault(getattr(person, index.ref_field), person)
    if len(matches) == 1:
        return next(iter(matches.values())), "DEMOGRAPHIC"
    return None, "AMBIGUOUS" if matches else "NO_MATCH"


def register_resolver(router, get_session, index: PersonIndex, source_system: str, resources: dict[str, Callable]) -> None:
    """Add ``POST /resolve/{record_type}`` to a department router. ``resources``
    maps each record type to the existing GET handler that serves it, so the
    record query itself is never duplicated."""

    @router.post("/resolve/{record_type}")
    def resolve_record(record_type: str, lookup: CanonicalLookup, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
        handler = resources.get(record_type)
        if handler is None:
            return JSONResponse(status_code=404, content={"sourceSystem": source_system, "synthetic": True, "disclaimer": SYNTHETIC_DISCLAIMER,
                                                          "correlationId": correlation_id, "retrievedAt": now_iso(), "status": "UNSUPPORTED_RECORD_TYPE", "data": None})
        person, method = find_person(session, index, lookup)
        if person is None:
            response = not_found(source_system, correlation_id)
            response.headers["X-Match-Result"] = method
            return response
        response = handler(citizen_ref=getattr(person, index.ref_field), correlation_id=correlation_id, session=session)
        if isinstance(response, JSONResponse):
            return response
        # The matched person's own identity as this department keeps it, so
        # SANGAM can re-check the match itself (it never takes it on trust).
        identity = {"name": getattr(person, index.name_field), "dob": getattr(person, index.dob_field),
                    "phone": getattr(person, index.phone_field) if index.phone_field else None}
        return {**response, "match": {"method": method, "departmentPersonId": getattr(person, index.id_field),
                                      "identity": {key: value for key, value in identity.items() if value}}}

    resolve_record.__name__ = f"resolve_{router.prefix.strip('/').replace('/', '_').replace('-', '_')}_record"
