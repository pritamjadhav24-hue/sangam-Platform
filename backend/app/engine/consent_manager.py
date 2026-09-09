from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

CONSENTS: dict[str, dict] = {}
PERMITTED = ["Income status", "Caste category", "Qualifying academic marks"]
EXCLUDED = ["Land records", "Individual bank transactions", "Biometrics"]


def create_consent(citizen_id: str, allow: bool, attributes: list[str] | None = None) -> dict:
    receipt_id = f"CR-{secrets.token_hex(3).upper()}"
    allowed = attributes or PERMITTED
    receipt = {"consentId": receipt_id, "citizenId": citizen_id, "consumer": "Higher Education Department", "purpose": "Scholarship eligibility assessment", "allowed": allowed if allow else [], "excluded": EXCLUDED, "decision": "ALLOW" if allow else "DENY", "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
    receipt["signature"] = hashlib.sha256(f"{receipt_id}{citizen_id}{receipt['expiresAt']}".encode()).hexdigest()
    CONSENTS[citizen_id] = receipt
    return receipt


def current(citizen_id: str): return CONSENTS.get(citizen_id)
