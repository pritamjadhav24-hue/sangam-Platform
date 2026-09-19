from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

CONSENTS: dict[str, dict] = {}
PERMITTED = ["Income status", "Caste category", "Qualifying academic marks"]
EXCLUDED = ["Land records", "Individual bank transactions", "Biometrics"]
CONSUMER = "Higher Education Department"
PURPOSE = "Scholarship eligibility assessment"


class ConsentAuthorizationError(ValueError):
    pass


def create_consent(citizen_id: str, allow: bool, attributes: list[str] | None = None, service_id: str | None = None, application_id: str | None = None, purpose: str | None = None) -> dict:
    receipt_id = f"CR-{secrets.token_hex(3).upper()}"
    allowed = attributes or PERMITTED
    unknown = [attribute for attribute in allowed if attribute not in PERMITTED]
    if unknown:
        raise ValueError(f"Unsupported consent attributes: {', '.join(unknown)}")
    receipt = {"consentId": receipt_id, "citizenId": citizen_id, "serviceId": service_id, "applicationId": application_id, "consumer": CONSUMER, "purpose": purpose or PURPOSE, "allowed": allowed if allow else [], "excluded": EXCLUDED, "decision": "ALLOW" if allow else "DENY", "createdAt": datetime.now(timezone.utc).isoformat(), "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
    receipt["signature"] = hashlib.sha256(f"{receipt_id}{citizen_id}{receipt['expiresAt']}".encode()).hexdigest()
    CONSENTS[citizen_id] = receipt
    return receipt


def current(citizen_id: str): return CONSENTS.get(citizen_id)


def authorize_access(citizen_id: str, consumer: str, purpose: str, requested_attributes: list[str] | None = None, service_id: str | None = None, application_id: str | None = None) -> dict:
    receipt = current(citizen_id)
    if not receipt or receipt.get("decision") != "ALLOW":
        raise ConsentAuthorizationError("Consent is missing or has not been granted.")
    if receipt.get("citizenId") != citizen_id:
        raise ConsentAuthorizationError("Consent identity does not match the requesting citizen.")
    if receipt.get("consumer") != consumer:
        raise ConsentAuthorizationError("Consent consumer does not match the requesting department.")
    if receipt.get("purpose") != purpose:
        raise ConsentAuthorizationError("Requested purpose is not covered by the consent receipt.")
    if service_id is not None and receipt.get("serviceId") != service_id:
        raise ConsentAuthorizationError("Consent is not bound to this service.")
    if application_id is not None and receipt.get("applicationId") not in {None, application_id}:
        raise ConsentAuthorizationError("Consent is not bound to this application.")
    try:
        expires_at = datetime.fromisoformat(receipt["expiresAt"])
    except (KeyError, ValueError):
        raise ConsentAuthorizationError("Consent expiry could not be validated.")
    if expires_at <= datetime.now(timezone.utc):
        raise ConsentAuthorizationError("Consent has expired.")
    requested = requested_attributes or []
    not_allowed = [attribute for attribute in requested if attribute not in receipt.get("allowed", [])]
    if not_allowed:
        raise ConsentAuthorizationError(f"Requested attributes are not covered by consent: {', '.join(not_allowed)}")
    return receipt


def revoke_consent(citizen_id: str, consent_id: str) -> dict:
    receipt = current(citizen_id)
    if not receipt or receipt.get("consentId") != consent_id:
        raise ConsentAuthorizationError("Consent receipt not found for this citizen.")
    receipt["decision"] = "REVOKED"
    receipt["allowed"] = []
    receipt["revokedAt"] = datetime.now(timezone.utc).isoformat()
    return receipt
