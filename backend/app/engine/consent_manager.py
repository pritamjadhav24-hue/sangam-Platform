from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

CONSENTS: dict[str, dict] = {}
# Legacy citizen-keyed compatibility view.  The authoritative local
# representation is keyed by consent ID so historical rows remain distinct.
CONSENTS_BY_ID: dict[str, dict] = {}
# Internal PostgreSQL source versions for every hydrated consent ID.  The
# citizen-keyed CONSENTS cache remains the legacy public/runtime shape.
CONSENT_SOURCE_VERSIONS: dict[str, int] = {}
PERMITTED = ["Income status", "Caste category", "Qualifying academic marks"]
EXCLUDED = ["Land records", "Individual bank transactions", "Biometrics"]
CONSUMER = "Higher Education Department"
PURPOSE = "Scholarship eligibility assessment"


class ConsentAuthorizationError(ValueError):
    pass


def _select_persisted_consent_row(session, citizen_id: str, consumer: str | None = None,
                                  purpose: str | None = None, service_id: str | None = None,
                                  application_id: str | None = None, consent_id: str | None = None,
                                  for_update: bool = False):
    from app.core.persistence import ConsentRow

    if not consent_id:
        return None
    query = session.query(ConsentRow).filter(ConsentRow.citizen_id == citizen_id)
    if consent_id:
        query = query.filter(ConsentRow.consent_id == consent_id)
        return (query.with_for_update() if for_update else query).first()


def create_consent(citizen_id: str, allow: bool, attributes: list[str] | None = None, service_id: str | None = None, application_id: str | None = None, purpose: str | None = None) -> dict:
    receipt_id = f"CR-{secrets.token_hex(3).upper()}"
    allowed = attributes or PERMITTED
    unknown = [attribute for attribute in allowed if attribute not in PERMITTED]
    if unknown:
        raise ValueError(f"Unsupported consent attributes: {', '.join(unknown)}")
    receipt = {"consentId": receipt_id, "citizenId": citizen_id, "serviceId": service_id, "applicationId": application_id, "consumer": CONSUMER, "purpose": purpose or PURPOSE, "allowed": allowed if allow else [], "excluded": EXCLUDED, "decision": "ALLOW" if allow else "DENY", "createdAt": datetime.now(timezone.utc).isoformat(), "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
    receipt["signature"] = hashlib.sha256(f"{receipt_id}{citizen_id}{receipt['expiresAt']}".encode()).hexdigest()
    CONSENTS_BY_ID[receipt_id] = receipt
    CONSENTS[citizen_id] = receipt
    from app.core.persistence import persist_consent
    persist_consent(receipt)
    return receipt


def current(citizen_id: str):
    candidates = [receipt for receipt in CONSENTS_BY_ID.values() if receipt.get("citizenId") == citizen_id]
    if len(candidates) == 1:
        return candidates[0]
    return None


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
    if service_id is not None and receipt.get("serviceId") not in {None, service_id}:
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


def authorize_persisted_access(citizen_id: str, consumer: str, purpose: str | None,
                               requested_attributes: list[str] | None = None,
                               service_id: str | None = None,
                               application_id: str | None = None,
                               consent_id: str | None = None) -> dict:
    """Authorize against the current PostgreSQL consent record.

    Async workers must not rely solely on the consent cache hydrated at process
    start. A missing database record is an authorization failure.
    """
    try:
        from sqlalchemy.orm import Session
        from app.core.persistence import ConsentRow, engine
        with Session(engine) as session:
            row = _select_persisted_consent_row(session, citizen_id, consumer, purpose, service_id, application_id, consent_id)
            receipt = row.payload if row else None
    except Exception as error:
        raise ConsentAuthorizationError("Persisted consent could not be validated.") from error
    if not receipt:
        raise ConsentAuthorizationError("Persisted consent is missing.")
    if consent_id and receipt.get("consentId") != consent_id:
        raise ConsentAuthorizationError("Consent receipt does not match the provider operation.")
    # Validate the persisted receipt without consulting the process-local cache.
    if receipt.get("decision") != "ALLOW" or receipt.get("citizenId") != citizen_id:
        raise ConsentAuthorizationError("Consent is missing, revoked, or has not been granted.")
    if receipt.get("consumer") != consumer or (purpose is not None and receipt.get("purpose") != purpose):
        raise ConsentAuthorizationError("Persisted consent scope does not match the provider operation.")
    if service_id is not None and receipt.get("serviceId") not in {None, service_id}:
        raise ConsentAuthorizationError("Consent is not bound to this service.")
    if application_id is not None and receipt.get("applicationId") not in {None, application_id}:
        raise ConsentAuthorizationError("Consent is not bound to this application.")
    try:
        expires_at = datetime.fromisoformat(receipt["expiresAt"])
    except (KeyError, ValueError) as error:
        raise ConsentAuthorizationError("Consent expiry could not be validated.") from error
    if expires_at <= datetime.now(timezone.utc) or receipt.get("revokedAt"):
        raise ConsentAuthorizationError("Consent has expired or was revoked.")
    requested = requested_attributes or []
    if any(attribute not in receipt.get("allowed", []) for attribute in requested):
        raise ConsentAuthorizationError("Requested attributes are not covered by persisted consent.")
    return receipt


def revoke_consent(citizen_id: str, consent_id: str) -> dict:
    from app.core.persistence import revoke_persisted_consent
    try:
        receipt = revoke_persisted_consent(citizen_id, consent_id)
    except KeyError as error:
        raise ConsentAuthorizationError("Consent is not persisted and cannot be revoked safely.") from error
    CONSENTS_BY_ID[consent_id] = receipt
    CONSENTS[citizen_id] = receipt
    return receipt


def execute_with_persisted_authorization(citizen_id: str, consumer: str, purpose: str | None,
                                         requested_attributes: list[str] | None = None,
                                         service_id: str | None = None,
                                         application_id: str | None = None,
                                         consent_id: str | None = None,
                                         operation=None):
    """Hold the PostgreSQL consent row lock through the provider call."""
    from sqlalchemy.orm import Session
    from app.core.persistence import ConsentRow, engine
    try:
        with Session(engine) as session:
            row = _select_persisted_consent_row(session, citizen_id, consumer, purpose, service_id, application_id, consent_id, for_update=True)
            receipt = row.payload if row else None
            if not receipt:
                raise ConsentAuthorizationError("Persisted consent is missing.")
            if consent_id and receipt.get("consentId") != consent_id:
                raise ConsentAuthorizationError("Consent receipt does not match the provider operation.")
            if receipt.get("decision") != "ALLOW" or receipt.get("citizenId") != citizen_id or receipt.get("revokedAt"):
                raise ConsentAuthorizationError("Consent is missing, revoked, or has not been granted.")
            if receipt.get("consumer") != consumer or (purpose is not None and receipt.get("purpose") != purpose):
                raise ConsentAuthorizationError("Persisted consent scope does not match the provider operation.")
            if service_id is not None and receipt.get("serviceId") not in {None, service_id}:
                raise ConsentAuthorizationError("Consent is not bound to this service.")
            if application_id is not None and receipt.get("applicationId") not in {None, application_id}:
                raise ConsentAuthorizationError("Consent is not bound to this application.")
            expires_at = datetime.fromisoformat(receipt["expiresAt"])
            if expires_at <= datetime.now(timezone.utc):
                raise ConsentAuthorizationError("Consent has expired.")
            requested = requested_attributes or []
            if any(attribute not in receipt.get("allowed", []) for attribute in requested):
                raise ConsentAuthorizationError("Requested attributes are not covered by persisted consent.")
            return operation() if operation else receipt
    except ConsentAuthorizationError:
        raise
    except Exception as error:
        raise ConsentAuthorizationError("Persisted consent could not be validated.") from error
