"""Synthetic identity-source mock backing the IDENTITY requirement.

Represents a state-level federated identity source, entirely synthetic. It
answers only for citizens SANGAM already knows about -- the legacy demo
citizen (CITIZEN_001) and any citizen registered in SANGAM's own citizen
master (CitizenRow), the same synthetic identity pool every other department
mock is deterministically derived from. No real government identity system
is contacted or represented.
"""
from app.mocks._citizen_lookup import lookup_citizen

LEGACY_IDENTITY_RECORD = {"recordId": "SRR-CITIZEN_001", "name": "Rahul Kumar", "dob": "2005-06-15", "gender": "MALE", "phone": "+91-9876543210", "district": "Pune", "validUntil": "2031-03-31", "signature": "SRR-IDENTITY-SIGNED"}


def get_identity(citizen_id: str):
    if citizen_id == "CITIZEN_001":
        return LEGACY_IDENTITY_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    return {"recordId": f"SRR-{citizen_id}", "name": citizen["name"], "dob": citizen["dob"], "gender": citizen.get("gender"), "phone": citizen.get("phone", ""), "district": citizen.get("district"), "validUntil": "2031-03-31", "signature": "SRR-IDENTITY-SIGNED"}
