"""Shared helpers for the classic department sandbox mocks.

These mocks originally only recognised a single hardcoded demo citizen
(CITIZEN_001). They now also answer for any citizen registered in SANGAM's
own citizen master (CitizenRow) -- the same synthetic identity pool every
other part of the platform already uses -- deterministically, so the same
citizen_id always gets the same synthetic record on every call. All data
returned by callers of these helpers remains entirely synthetic/demo data;
no real citizen or government data is used or referenced.
"""
from __future__ import annotations

import hashlib


def lookup_citizen(citizen_id: str) -> dict | None:
    from app.core.persistence import CitizenRow, Session, engine
    with Session(engine) as session:
        row = session.get(CitizenRow, citizen_id)
        if row is None:
            return None
        return {"citizenId": row.citizen_id, "name": row.full_name, "dob": row.date_of_birth, "gender": row.gender, "phone": row.phone or "", "district": row.district, "persona": row.persona}


def stable_choice(citizen_id: str, salt: str, low: int, high: int) -> int:
    """Deterministic pseudo-random integer in [low, high], stable per (citizen_id, salt)."""
    digest = hashlib.sha256(f"{citizen_id}:{salt}".encode()).hexdigest()
    return low + (int(digest[:8], 16) % (high - low + 1))
