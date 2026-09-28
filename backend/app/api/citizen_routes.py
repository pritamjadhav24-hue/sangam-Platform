from __future__ import annotations

import hashlib
import re
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit_bus import audit_bus
from fastapi.security import HTTPAuthorizationCredentials
from app.core.auth import _bearer, decode_token, require_roles
from app.core.event_bus import event_bus
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent, current, revoke_consent
from app.engine.dependency_orchestrator import ensure_missing_dependencies, initiate_dependency
from app.core.persistence import (citizen_service_snapshot, catalog_snapshot, create_citizen_notification, engine,
                                  delete_document, get_application, get_document, list_applications_for_citizen,
                                  list_dependencies_for_application,
                                  create_application as create_application_authoritative,
                                  mark_application_write_authoritative, upsert_document)
from app.engine.artifact_retrieval import (UPLOAD_FILE_SIGNATURES, citizen_safe_document_text, decode_upload_file, document_display_name,
                                            requirement_data_type, safe_upload_filename, validate_upload_metadata)
from app.engine import eligibility, requirement_fulfillment, submission
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import APPLICATIONS, create_application, find_active_application, transition_application
from app.core.rate_limit import enforce

router = APIRouter(prefix="/api/citizen", tags=["Citizen"])


class Consent(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    allow: bool
    attributes: Optional[List[str]] = None
    schemeId: Optional[str] = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    purpose: Optional[str] = Field(default=None, max_length=240)


class Dependency(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    appId: Optional[str] = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    requirementCode: Optional[str] = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class Submit(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    appId: Optional[str] = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    simulateTimeout: bool = False


class RevokeConsent(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    consentId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class DocumentUpload(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    appId: Optional[str] = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    requirementCode: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    contentType: str = Field(default="text/plain", max_length=60)
    content: str = Field(min_length=1, max_length=200_000)


class ApplicationCreate(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    serviceId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    purpose: Optional[str] = Field(default=None, max_length=240)
    attributes: Optional[List[str]] = None


class ApplySchemeRequest(BaseModel):
    """Note: deliberately has NO citizenId field -- the applicant is always the
    authenticated JWT subject, never a value supplied by the client."""
    schemeId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class RequirementUpload(BaseModel):
    """``content`` is plain text for text/plain / application/json, or the
    base64-encoded file for image/jpeg, image/png and application/pdf
    (device upload or camera capture, at most 5 MB decoded)."""
    title: str = Field(min_length=1, max_length=200)
    contentType: str = Field(default="text/plain", max_length=60)
    content: str = Field(min_length=1, max_length=7_200_000)
    fileName: Optional[str] = Field(default=None, max_length=200)


class AutoFillDecision(BaseModel):
    """The citizen's response to the Auto-Fill consent dialog. Defaults to
    ACCEPT so the existing Phase 6B call shape (no body) keeps working."""
    decision: Literal["ACCEPT", "REJECT"] = "ACCEPT"


def _record_discovery(citizen_id: str, result: dict, app_id: Optional[str] = None) -> None:
    for item in result["requirements"]:
        audit_bus.append(citizen_id, item["code"], "Configured service requirement discovery", item["source"], "PROBE", payload=item.get("canonical", {}), correlation_id=app_id)
        if item["status"] == "FOUND":
            event_bus.publish(f"{item['code']}_VERIFIED", {"citizenId": citizen_id, "appId": app_id, "requirement": item["code"]})


def _record_entity_reviews(app: dict) -> None:
    for review in app.get("entityReviews", []):
        if review.get("auditRecorded"):
            continue
        audit_bus.append(app["citizenId"], "ENTITY_RESOLUTION", "Medium-confidence cross-system match requires human review", review["source"], "REVIEW_REQUIRED", app.get("consentId"), payload={"reviewId": review["reviewId"], "appId": app["appId"], "requirementCode": review["requirementCode"], "sourceRecordId": review["sourceRecordId"], "confidenceScore": review["confidenceScore"], "confidenceLevel": review["confidenceLevel"]}, correlation_id=app["appId"])
        review["auditRecorded"] = True


def _require_consent(citizen_id: str, purpose: str = PURPOSE, attributes: Optional[List[str]] = None, service_id: Optional[str] = None, application_id: Optional[str] = None) -> dict:
    try:
        return authorize_access(citizen_id, CONSUMER, purpose, attributes, service_id=service_id, application_id=application_id)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=403, detail=f"Protected access denied: {error}")


def _assert_own_citizen(user: dict, citizen_id: str) -> None:
    if user.get("role") != "CITIZEN" or user.get("citizenId") != citizen_id:
        raise HTTPException(status_code=403, detail="Citizens may access only their own services.")


@router.get("/schemes")
def schemes(user: dict = Depends(require_roles("CITIZEN"))):
    configured = citizen_service_snapshot()
    return {"schemes": configured, "services": configured}


@router.get("/services")
def services(user: dict = Depends(require_roles("CITIZEN"))):
    return {"services": citizen_service_snapshot() or []}


@router.get("/services/{service_id}")
def service_detail(service_id: str, user: dict = Depends(require_roles("CITIZEN"))):
    service = citizen_service_snapshot(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Configured service not found")
    return service


@router.get("/discover")
def discovery(citizen_id: str = "CITIZEN_001", simulate_timeout: bool = False, scheme_id: Optional[str] = None, purpose: Optional[str] = None, attributes: Optional[List[str]] = None, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, citizen_id)
    citizen = user if user.get("citizenId") == citizen_id else None
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    if purpose is not None or attributes:
        if not purpose:
            raise HTTPException(status_code=403, detail="Protected access denied: a purpose is required.")
        _require_consent(citizen_id, purpose, attributes)
    result = discover({k: v for k, v in citizen.items() if k != "password"}, simulate_timeout, scheme_id)
    app = find_active_application(citizen_id)
    _record_discovery(citizen_id, result, app["appId"] if app else None)
    return _safe_discovery(result)


def _safe_discovery(result: dict) -> dict:
    """Return only citizen-actionable discovery state.

    Provider records, mapping evidence, source identifiers, and resolution
    internals remain server-side for workflow/audit purposes.
    """
    service = result.get("service") or {}
    requirements = []
    for item in result.get("requirements", []):
        requirements.append({
            "requirementCode": item.get("code"),
            "displayLabel": item.get("label") or str(item.get("code", "")).replace("_", " ").title(),
            "status": item.get("status"),
            "userAction": item.get("action") or ("No action required" if item.get("status") == "FOUND" else "Retry verification or request help"),
        })
    return {
        "serviceId": result.get("serviceId") or result.get("schemeId"),
        "service": {field: service.get(field) for field in ("serviceId", "name", "department") if service.get(field) is not None},
        "requirements": requirements,
        "conflicts": [{"status": item.get("status"), "field": item.get("canonicalField"), "message": "Additional review is required."} for item in result.get("conflicts", [])],
        "resilienceBanner": result.get("resilienceBanner"),
    }


_REQUIREMENT_USER_ACTION = {
    "FOUND": "No action required", "VALIDATED": "No action required", "RETRIEVED": "No action required",
    "NOT_PROVIDED": "Use Auto-Fill or Manual Upload to provide this.",
    # ACTION_REQUIRED covers two distinct causes (the citizen declined the
    # Auto-Fill consent prompt, or retries were exhausted after repeated
    # failures) -- one persisted, refresh-safe message that reads correctly
    # for both, matching the citizen-facing wording this phase specifies.
    "ACTION_REQUIRED": "Automatic retrieval was not allowed. You can provide this manually.",
    # REJECTED is different: the provider actually returned data, but it
    # failed validation -- nothing was "not allowed", it just didn't verify.
    "REJECTED": "The retrieved information could not be verified. You can provide this manually.",
    "WAITING": "Retrieval is in progress. You can try again shortly.",
    "FAILED": "Automatic retrieval could not complete. You can provide this manually.",
}

_NEEDS_ATTENTION_REQUIREMENT_STATUSES = frozenset({"ACTION_REQUIRED", "FAILED"})


# Requirement types a citizen may evidence with their own upload: documents
# and certificates, and department records (a supporting document such as a
# marksheet or bank passbook, reviewed by an officer). An identity attribute
# is not uploadable -- it comes from the identity registry.
UPLOADABLE_DATA_TYPES = frozenset({"DOCUMENT", "CERTIFICATE", "RECORD"})


def _can_upload(requirement: dict) -> bool:
    data_type = requirement.get("dataType")
    if data_type is None:
        from app.engine.artifact_retrieval import requirement_data_type
        data_type = requirement_data_type(requirement.get("code") or "")
    return data_type in UPLOADABLE_DATA_TYPES


_OUTAGE_CATEGORIES = frozenset({"UPSTREAM_UNAVAILABLE", "NETWORK_ERROR", "UPSTREAM_ERROR", "RATE_LIMITED"})


def _verification_state(requirement: dict) -> str:
    """One explicit, citizen-safe verification state -- so "no record",
    "temporarily unavailable", "not confident it is you" and "you declined"
    are never collapsed into the same message.

    NOT_STARTED, CHECKING, VERIFIED, VERIFIED_VIA_FALLBACK, UPLOADED,
    NO_RECORD, TEMPORARILY_UNAVAILABLE, TIMEOUT, UNAUTHORIZED, CONSENT_DENIED,
    LOW_CONFIDENCE, AMBIGUOUS_MATCH, VERIFICATION_FAILED, MANUAL_UPLOAD_REQUIRED."""
    status, category = requirement.get("status"), requirement.get("errorCategory")
    if status in {"VALIDATED", "RETRIEVED", "FOUND"}:
        if requirement.get("documentId"):
            return "UPLOADED"
        return "VERIFIED_VIA_FALLBACK" if (requirement.get("provenance") or {}).get("fallbackUsed") else "VERIFIED"
    if status == "PROCESSING" or (requirement.get("autoFillRequestedAt") and status in {None, "NOT_PROVIDED"}):
        return "CHECKING"
    if status in {None, "NOT_PROVIDED"}:
        return "NOT_STARTED"
    if category == "IDENTITY_UNCONFIRMED":
        return "LOW_CONFIDENCE"
    if category == "TIMEOUT":
        return "TIMEOUT"
    if category in _OUTAGE_CATEGORIES:
        return "TEMPORARILY_UNAVAILABLE"
    if category in {"AUTHORIZATION_ERROR", "AUTHENTICATION_ERROR"}:
        return "UNAUTHORIZED"
    if category == "VALIDATION_ERROR":
        return "AMBIGUOUS_MATCH" if requirement.get("lookupOutcome") == "AMBIGUOUS" else "NO_RECORD"
    if status == "REJECTED":
        return "VERIFICATION_FAILED"
    if status == "ACTION_REQUIRED" and not category:
        return "CONSENT_DENIED"
    if status in {"FAILED", "ACTION_REQUIRED", "WAITING"}:
        return "MANUAL_UPLOAD_REQUIRED"
    return "IN_PROGRESS"


_STATE_MESSAGES = {
    "NO_RECORD": "No verified record was found in the connected departments.",
    "TEMPORARILY_UNAVAILABLE": "Government verification is temporarily unavailable.",
    "TIMEOUT": "The government department took too long to respond.",
    "LOW_CONFIDENCE": "We couldn't verify this record with sufficient confidence.",
    "AMBIGUOUS_MATCH": "More than one record matched your details, so it couldn't be verified automatically.",
    "UNAUTHORIZED": "Automatic retrieval is not authorized for this record.",
    "CONSENT_DENIED": "You chose not to allow automatic retrieval.",
    "VERIFICATION_FAILED": "The retrieved information could not be verified.",
    "MANUAL_UPLOAD_REQUIRED": "Automatic verification could not be completed.",
}
_UPLOAD_SENTENCE = " You can upload the document yourself."


def _requirement_user_action(requirement: dict) -> str:
    """ACTION_REQUIRED after exhausted retries carries the failure's error
    category; after a declined consent it does not. Only the wording differs
    -- no provider or failure detail ever reaches the citizen."""
    state = _verification_state(requirement)
    if state in _STATE_MESSAGES:
        message = _STATE_MESSAGES[state]
        if _can_upload(requirement):
            return message + _UPLOAD_SENTENCE
        return message + (" You can try Auto-Fill again at any time." if state == "CONSENT_DENIED" else " Please try again later.")
    return _REQUIREMENT_USER_ACTION.get(requirement.get("status"), "Retry verification or request help")


# Entity resolution could not confirm the department record is this
# citizen's (it is never attached); and "no record exists" (a department
# answered, it simply holds nothing for this citizen).
IDENTITY_UNCONFIRMED_MESSAGE = "We couldn't verify this record with sufficient confidence. You can upload the document yourself."
NO_RECORD_MESSAGE = "No verified record was found in the connected departments. You can upload the document yourself."
UNAVAILABLE_MESSAGE = "Government verification is temporarily unavailable. You can upload the document yourself."


# A requirement waiting because the verification it needs is unavailable
# (an outage, not a problem with the citizen's data). The citizen is told
# only that -- never which department, provider or system is down.
_OUTAGE_ERROR_CATEGORIES = frozenset({"UPSTREAM_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT", "UPSTREAM_ERROR", "RATE_LIMITED"})
VERIFICATION_DELAYED_MESSAGE = ("Your application is temporarily delayed because one of the required verifications is currently "
                                "unavailable. Your application has been retained; please try again later.")


def _verification_delayed(requirement: dict) -> bool:
    return requirement.get("status") == "WAITING" and requirement.get("errorCategory") in _OUTAGE_ERROR_CATEGORIES


def _notify_requirement_outcome(citizen_id: str, application_id: str, requirement_code: str, label: str, previous_status: str | None, new_status: str | None) -> None:
    """Phase 6F2 Task E: a persisted citizen notification for exactly the
    two requirement outcomes that need one -- Auto-Fill/upload needing
    attention, and a document becoming verified -- fired only on an actual
    status change (never repeated on a redundant retry/no-op call)."""
    if new_status == previous_status:
        return
    if new_status in _NEEDS_ATTENTION_REQUIREMENT_STATUSES:
        doc_like = requirement_data_type(requirement_code) in {"DOCUMENT", "CERTIFICATE"}
        name = document_display_name(label) if doc_like else label
        message = (f"Your {name} could not be retrieved automatically. Please upload it manually." if doc_like
                    else f"We could not verify your {name} automatically. Please try again later.")
        create_citizen_notification(citizen_id, "ACTION_REQUIRED", "Action needed", message, application_id=application_id, requirement_code=requirement_code)
    elif new_status == "VALIDATED":
        name = document_display_name(label)
        create_citizen_notification(citizen_id, "DOCUMENT_VERIFIED", "Document verified", f"Your {name} has been verified.", application_id=application_id, requirement_code=requirement_code)


def _verified_source(requirement: dict) -> dict:
    if requirement.get("documentId") or requirement.get("status") not in {"VALIDATED", "RETRIEVED"} or not requirement.get("sourceDepartment"):
        return {}
    from app.engine.departments import department_label
    key = requirement["sourceDepartment"]
    provenance = requirement.get("provenance") or {}
    # Citizen-safe provenance only: which department, when, whether an
    # alternate government source answered, and whether it was a record or a
    # department-issued file -- never provider, API or match internals.
    return {"source": department_label(key), "sourceMr": department_label(key, "mr"), "verifiedAt": requirement.get("verifiedAt"),
            "alternateSource": bool(provenance.get("fallbackUsed", requirement.get("isFallback"))),
            "recordKind": provenance.get("recordKind", "STRUCTURED_RECORD")}


def _safe_application(app: dict, eligibility_cache: Optional[dict] = None) -> dict:
    safe_requirements = []
    for requirement in app.get("requirements", []):
        safe_requirements.append({
            "requirementCode": requirement.get("code"),
            "displayLabel": requirement.get("label") or str(requirement.get("code", "")).replace("_", " ").title(),
            "displayLabelMr": requirement.get("labelMr") or requirement.get("label") or str(requirement.get("code", "")).replace("_", " ").title(),
            "status": requirement.get("status"),
            "userAction": requirement.get("action") or _requirement_user_action(requirement),
            "verificationState": _verification_state(requirement),
            "canUpload": _can_upload(requirement),
            **({"verifiedOn": requirement.get("verifiedOn")} if requirement.get("verifiedOn") else {}),
            # Phase 6B dynamic form fields -- present only on applications created
            # through the new /apply boundary; never exposes provider/department/
            # document-source information, only the requirement's own shape/state.
            **({"mandatory": requirement.get("mandatory")} if "mandatory" in requirement else {}),
            **({"dataType": requirement.get("dataType")} if "dataType" in requirement else {}),
            **({"documentId": requirement.get("documentId")} if requirement.get("documentId") else {}),
            # Which department verified it (never which system/API), shown as
            # "Source: Revenue Department". Not for the citizen's own upload.
            **_verified_source(requirement),
        })
    safe_conflicts = [{"status": item.get("status"), "field": item.get("canonicalField"), "message": "Additional review is required."} for item in app.get("conflicts", [])]
    safe_dependencies = []
    for dependency_item in app.get("dependencies", []):
        safe_dependencies.append({field: dependency_item.get(field) for field in ("requiredService", "serviceName", "status", "attempts", "maxAttempts") if field in dependency_item})
    safe = {field: app.get(field) for field in ("appId", "serviceId", "schemeId", "schemeName", "status", "consentId", "createdAt", "updatedAt") if field in app}
    safe["citizenId"] = None
    safe["requirements"] = safe_requirements
    safe["conflicts"] = safe_conflicts
    safe["entityReviews"] = []
    safe["conflictReviews"] = []
    safe["dependencies"] = safe_dependencies
    if isinstance(app.get("eligibility"), dict):
        safe["eligibility"] = {field: app["eligibility"].get(field) for field in ("eligible", "reasons") if field in app["eligibility"]}
    # Deterministic scheme eligibility (app.engine.eligibility): outcome and
    # per-criterion reasons only -- no provider, source or rule internals.
    safe["eligibilityAssessment"] = eligibility.citizen_view(eligibility.assess_application(app, eligibility_cache))
    safe["verificationDelayed"] = any(_verification_delayed(item) for item in app.get("requirements", []))
    if isinstance(app.get("statusHistory"), list):
        safe["statusHistory"] = [{field: item.get(field) for field in ("status", "at") if field in item} for item in app["statusHistory"]]
    # Phase 6E: every read of an application (apply/auto-fill/upload/get)
    # already carries whether it is ready to submit, computed from the same
    # canonical readiness rule the actual submission endpoint enforces --
    # the Review page needs no separate endpoint or a second definition of
    # "complete". Only citizen-safe requirement fields (already built above)
    # are echoed back for the blocking list.
    readiness = submission.evaluate_submission_readiness(app)
    safe["readyForSubmission"] = readiness["ready"] and app.get("status") == submission.SUBMITTABLE_STATUS
    safe["blockingRequirements"] = [item for item in safe_requirements if item["requirementCode"] in set(readiness["blockingCodes"])]
    if app.get("status") == submission.SUBMITTED_STATUS:
        safe["submittedAt"] = app.get("updatedAt")
    return safe


def _application_with_database_dependencies(app: dict, session: Session) -> dict:
    """Build the response projection from the same PostgreSQL read session."""
    application = dict(app)
    dependencies = list_dependencies_for_application(application["appId"], session=session)
    application["dependencies"] = dependencies
    application["dependencyIds"] = [item["dependencyId"] for item in dependencies]
    return application


def _safe_consent(receipt: dict) -> dict:
    return {field: receipt.get(field) for field in ("consentId", "serviceId", "purpose", "allowed", "decision", "createdAt", "expiresAt", "revokedAt", "appId", "applicationStatus") if field in receipt}


def _safe_workflow_events(events: list[dict], app_id: str) -> list[dict]:
    safe_types = {
        "DEPENDENCY_RESOLVED": ("VERIFICATION_COMPLETED", "Verification completed."),
        "DOMICILE_ISSUED": ("VERIFICATION_COMPLETED", "Verification completed."),
        "PROVIDER_JOB_RETRYING": ("VERIFICATION_DELAYED", "Verification is delayed."),
        "PROVIDER_JOB_DEAD_LETTER": ("VERIFICATION_DELAYED", "Verification is delayed; further review may be required."),
        "PROVIDER_JOB_CANCELLED": ("APPLICATION_UPDATED", "Verification was cancelled and may require renewed consent."),
        "DEPENDENCY_SERVICE_FAILED": ("VERIFICATION_DELAYED", "Verification is delayed."),
        "APPLICATION_SUBMITTED": ("APPLICATION_UPDATED", "Application updated."),
        "APPLICATION_STATUS_CHANGED": ("APPLICATION_UPDATED", "Application updated."),
        "WORKFLOW_RESUMED": ("APPLICATION_UPDATED", "Application updated."),
    }
    safe_events = []
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("appId") != app_id:
            continue
        safe_type, message = safe_types.get(event.get("type"), ("APPLICATION_UPDATED", "Application updated."))
        safe_events.append({
            "type": safe_type,
            "occurredAt": event.get("occurredAt"),
            "message": message,
        })
    return safe_events


@router.post("/applications")
def create_citizen_application(body: ApplicationCreate, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    enforce("application_create", body.citizenId, limit=10, window_seconds=60)
    service = citizen_service_snapshot(body.serviceId)
    if not service:
        raise HTTPException(status_code=404, detail="Configured service not found or disabled")
    receipt = _require_consent(body.citizenId, body.purpose or PURPOSE, body.attributes, service_id=body.serviceId)
    citizen = {k: v for k, v in user.items() if k != "password"}
    result = discover(citizen, service_id=body.serviceId)
    app = create_application(body.citizenId, result, evaluate(result["requirements"]), body.serviceId)
    app["consentId"] = receipt["consentId"]
    app["consentAttributes"] = list(receipt.get("allowed", []))
    _record_discovery(body.citizenId, result, app["appId"])
    _record_entity_reviews(app)
    ensure_missing_dependencies(app)
    audit_bus.append(body.citizenId, "APPLICATION", "Configured service application created", "GovOrchestrator", "CREATE", receipt["consentId"], payload={"appId": app["appId"], "serviceId": body.serviceId, "actorRole": user["role"]}, correlation_id=app["appId"])
    return _safe_application(app)


@router.get("/profile")
def citizen_profile(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer), user: dict = Depends(require_roles("CITIZEN"))):
    """The signed-in citizen's own profile: their record in the citizen
    register (or their account details) and the current session."""
    from datetime import datetime, timezone
    from app.core.persistence import CitizenRow
    citizen_id = user["citizenId"]
    with Session(engine) as session:
        row = session.get(CitizenRow, citizen_id)
        record = ({"name": row.full_name, "dob": row.date_of_birth, "gender": row.gender, "phone": row.phone,
                   "district": row.district, "address": (row.payload or {}).get("address")} if row else
                  {key: user.get(key) for key in ("name", "dob", "phone", "district")})
    claims = decode_token(credentials.credentials)
    as_iso = lambda seconds: datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    return {"citizenId": citizen_id, **{key: value for key, value in record.items() if value},
            "accountStatus": "Active", "verifiedIdentity": row is not None,
            "session": {"signedInAt": as_iso(claims["iat"]), "expiresAt": as_iso(claims["exp"])}}


@router.get("/applications")
def list_citizen_applications(user: dict = Depends(require_roles("CITIZEN"))):
    with Session(engine) as session:
        applications = list_applications_for_citizen(user.get("citizenId"), session=session)
        cache: dict = {}  # scheme rules + profile read once for the whole list
        return {"applications": [_safe_application(_application_with_database_dependencies(app, session), cache) for app in applications]}


@router.get("/applications/{application_id}")
def get_citizen_application(application_id: str, user: dict = Depends(require_roles("CITIZEN"))):
    with Session(engine) as session:
        app = get_application(application_id, session=session)
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app.get("citizenId") != user.get("citizenId"):
            raise HTTPException(status_code=404, detail="Application not found")
        return _safe_application(_application_with_database_dependencies(app, session))


def _load_owned_application(application_id: str, citizen_id: str) -> dict:
    """PostgreSQL-authoritative read + ownership check, shared by the Phase 6B
    form endpoints (mirrors get_citizen_application's own check)."""
    app = get_application(application_id)
    if not app or app.get("citizenId") != citizen_id:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _assert_application_not_submitted(app: dict) -> None:
    """Fast-path rejection before any provider call/consent is created.

    This is a courtesy check only -- the real, race-proof enforcement is the
    fresh, lock-protected status check inside requirement_fulfillment.
    mutate_requirement_under_lock, which every requirement-mutating path
    routes through regardless of this early check.
    """
    if app.get("status") == submission.SUBMITTED_STATUS:
        raise HTTPException(status_code=409, detail="This application has already been submitted and can no longer be changed.")


@router.post("/apply")
def apply_to_scheme(body: ApplySchemeRequest, request: Request, user: dict = Depends(require_roles("CITIZEN"))):
    """Dynamic application-form entry point (Phase 6B).

    Creates a PostgreSQL-authoritative application (never trusting a
    client-supplied citizen id -- the applicant is always the authenticated
    JWT subject) whose requirement list is built entirely from the selected
    scheme's own catalog requirements, not from any per-scheme frontend code.
    Idempotent: re-applying to a scheme with an already-open application
    returns that same application rather than creating a duplicate.
    """
    citizen_id = user["citizenId"]
    enforce("apply", citizen_id, limit=10, window_seconds=60)
    scheme = citizen_service_snapshot(body.schemeId)
    if not scheme or scheme.get("enabled") is False:
        raise HTTPException(status_code=404, detail="Configured scheme not found or disabled")

    terminal = {"COMPLETED", "REJECTED", "CANCELLED"}
    with Session(engine) as session:
        existing = [
            app for app in list_applications_for_citizen(citizen_id, session=session)
            if app.get("serviceId") == body.schemeId and app.get("status") not in terminal
        ]
        if existing:
            application = existing[0]
            created = False
        else:
            requirements = [
                {
                    "code": item["code"],
                    "label": item.get("label") or str(item["code"]).replace("_", " ").title(),
                    "labelMr": item.get("labelMr") or item.get("label") or str(item["code"]).replace("_", " ").title(),
                    "mandatory": item.get("mandatory", True),
                    "status": "NOT_PROVIDED",
                    "dataType": requirement_data_type(item["code"]),
                }
                for item in scheme.get("requirements", [])
            ]
            application = create_application_authoritative(
                {
                    "citizenId": citizen_id,
                    "serviceId": body.schemeId,
                    "status": "IN_PROGRESS",
                    "schemeName": scheme.get("name"),
                    "requirements": requirements,
                },
                session=session,
            )
            mark_application_write_authoritative(request)
            created = True
        session.commit()

    audit_bus.append(
        citizen_id, "APPLICATION", "Citizen opened a scheme application form", "GovOrchestrator",
        "CREATE" if created else "RESUME", payload={"appId": application["appId"], "schemeId": body.schemeId, "actorRole": user["role"]},
        correlation_id=application["appId"],
    )
    return _safe_application(application)


@router.post("/applications/{application_id}/requirements/{requirement_code}/auto-fill")
def auto_fill_requirement(application_id: str, requirement_code: str, body: AutoFillDecision = AutoFillDecision(), user: dict = Depends(require_roles("CITIZEN"))):
    """Per-requirement Auto-Fill action boundary (Phase 6B boundary, Phase 6C
    real execution).

    Establishes the exact application + requirement the action applies to,
    never trusting any provider/department selection from the caller. The
    citizen's consent decision (Accept/Reject, from a dialog the frontend
    shows before calling this) drives two completely different paths:

    - REJECT: no consent is created, no provider is ever called -- see
      requirement_fulfillment.reject_auto_fill.
    - ACCEPT: a fresh, requirement-scoped consent receipt is recorded (the
      existing versioned consent implementation, unmodified), then
      requirement_fulfillment.fulfill_requirement runs the real pipeline --
      dynamic provider discovery -> adapter -> schema mapping -> validation
      -- and persists the outcome through the PostgreSQL-authoritative
      mutation gateway (mutate_application), the same gateway the Phase 6B
      manual-upload endpoint already uses, since this application's
      authoritative_at is set from creation and the legacy dependency path
      (ensure_dependency/initiate_dependency) cannot write to it.

    Each request here is independent per (application_id, requirement_code):
    concurrent Auto-Fill calls for different requirements on the same
    application run on separate threads (FastAPI/Starlette's threadpool for
    synchronous route handlers) and only serialize briefly at the final
    application-row write, never for the duration of the provider call
    itself -- so one requirement's retrieval never blocks or is cancelled by
    another's.
    """
    citizen_id = user["citizenId"]
    enforce("auto_fill", citizen_id, limit=20, window_seconds=60)
    app = _load_owned_application(application_id, citizen_id)
    _assert_application_not_submitted(app)
    requirement = requirement_fulfillment.find_requirement(app, requirement_code)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found on this application")

    if body.decision == "REJECT":
        previous_status = requirement.get("status")
        label = requirement.get("label") or requirement_code
        try:
            application = requirement_fulfillment.reject_auto_fill(app, requirement_code, citizen_id)
        except requirement_fulfillment.ApplicationSubmittedError:
            raise HTTPException(status_code=409, detail="This application has already been submitted and can no longer be changed.")
        audit_bus.append(
            citizen_id, requirement_code, "Citizen declined automatic retrieval for a requirement", "GovOrchestrator",
            "AUTO_FILL_REJECTED", payload={"appId": application_id, "requirementCode": requirement_code, "actorRole": user["role"]},
            correlation_id=application_id,
        )
        updated_requirement = requirement_fulfillment.find_requirement(application, requirement_code)
        _notify_requirement_outcome(citizen_id, application_id, requirement_code, label, previous_status, (updated_requirement or {}).get("status"))
        return _safe_application(application)

    if requirement.get("status") in requirement_fulfillment.SUCCESS_STATUSES:
        return _safe_application(app)

    previous_status = requirement.get("status")
    label = requirement.get("label") or requirement_code
    receipt = create_consent(
        citizen_id, True, attributes=[], service_id=app.get("serviceId"), application_id=application_id,
        purpose=requirement_fulfillment.auto_fill_purpose(requirement_code),
    )
    audit_bus.append(
        citizen_id, requirement_code, "Citizen granted consent for Auto-Fill", "GovOrchestrator",
        "CONSENT_GRANTED", receipt["consentId"], payload={"appId": application_id, "requirementCode": requirement_code, "actorRole": user["role"]},
        correlation_id=application_id,
    )

    try:
        application = requirement_fulfillment.fulfill_requirement(app, requirement_code, citizen_id, receipt["consentId"], correlation_id=application_id)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=403, detail=f"Protected access denied: {error}")
    except requirement_fulfillment.ApplicationSubmittedError:
        # A submission committed between this request's own provider call
        # and its attempt to persist the result -- the result is discarded,
        # never applied to an application the citizen can no longer edit.
        raise HTTPException(status_code=409, detail="This application has already been submitted and can no longer be changed.")

    updated_requirement = requirement_fulfillment.find_requirement(application, requirement_code)
    # Attribute the audit source to the actual department/provider SANGAM
    # retrieved from (already recorded on the requirement as providerId),
    # falling back to GovOrchestrator only when no provider was ever
    # reached (e.g. rejected before discovery).
    audit_source = (updated_requirement or {}).get("providerId") or "GovOrchestrator"
    audit_bus.append(
        citizen_id, requirement_code, "Auto-Fill retrieval attempt completed", audit_source,
        (updated_requirement or {}).get("status", "UNKNOWN"), receipt["consentId"],
        payload={"appId": application_id, "requirementCode": requirement_code, "status": (updated_requirement or {}).get("status"), "providerId": (updated_requirement or {}).get("providerId"), "actorRole": user["role"]},
        correlation_id=application_id,
    )
    _notify_requirement_outcome(citizen_id, application_id, requirement_code, label, previous_status, (updated_requirement or {}).get("status"))
    return _safe_application(application)


@router.post("/applications/{application_id}/requirements/{requirement_code}/upload")
def upload_requirement_document(application_id: str, requirement_code: str, body: RequirementUpload, user: dict = Depends(require_roles("CITIZEN"))):
    """Per-requirement manual upload (Phase 6B).

    Reuses Phase 4's artifact-integrity validation and document reference
    model (validate_upload_metadata, upsert_document) but persists the
    requirement-state change through the PostgreSQL-authoritative mutation
    gateway (mutate_application) rather than the legacy in-memory dependency
    path, since this application is authoritative from creation.

    Uses the same requirement_fulfillment.mutate_requirement_under_lock
    helper Auto-Fill uses (Phase 6D): reading the requirements list inside
    the same row lock that writes it prevents a concurrent Auto-Fill (or
    another upload) for a *different* requirement on this application from
    losing this update, or vice versa. A manual upload is an explicit
    citizen action and always wins here -- it is not skipped even if the
    requirement already has a successful Auto-Fill result -- but a stale,
    slower Auto-Fill outcome that finishes *after* this upload can never
    downgrade it in turn, because requirement_fulfillment._apply_outcome
    checks the requirement's freshly-locked status before applying any
    outcome and is a no-op once the requirement is already VALIDATED.
    """
    citizen_id = user["citizenId"]
    enforce("requirement_upload", citizen_id, limit=10, window_seconds=60)
    app = _load_owned_application(application_id, citizen_id)
    _assert_application_not_submitted(app)
    requirement = requirement_fulfillment.find_requirement(app, requirement_code)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found on this application")
    if not _can_upload(requirement):
        raise HTTPException(status_code=400, detail="This requirement does not accept a manual document upload")

    artifact = {"title": body.title, "contentType": body.contentType, "content": body.content}
    integrity = validate_upload_metadata(artifact)
    if not integrity["valid"]:
        raise HTTPException(status_code=422, detail={"reasons": integrity["reasons"]})

    is_file = body.contentType in UPLOAD_FILE_SIGNATURES
    file_bytes = decode_upload_file(body.content) if is_file else None
    checksum = hashlib.sha256(file_bytes if is_file else body.content.encode("utf-8")).hexdigest()
    document_id = f"DOC-{application_id}-{requirement_code}"
    canonical = {"title": body.title, "contentType": body.contentType, "checksum": checksum}
    file_fields = {}
    if is_file:
        file_name = safe_upload_filename(body.fileName, body.contentType)
        canonical.update({"fileName": file_name, "sizeBytes": len(file_bytes)})
        # Stored (base64) on the document reference itself; only the
        # authenticated owner's download route ever returns it.
        encoded = body.content.split(",", 1)[1] if body.content.startswith("data:") else body.content
        file_fields = {"fileName": file_name, "sizeBytes": len(file_bytes), "fileContent": encoded}
    previous_status = requirement.get("status")
    label = requirement.get("label") or requirement_code

    def mutate(target: dict) -> None:
        target.update({"status": "VALIDATED", "documentId": document_id})
        target.pop("autoFillRequestedAt", None)

    try:
        application, _ = requirement_fulfillment.mutate_requirement_under_lock(application_id, requirement_code, mutate)
    except requirement_fulfillment.ApplicationSubmittedError:
        raise HTTPException(status_code=409, detail="This application has already been submitted and can no longer be changed.")
    upsert_document({
        "documentId": document_id, "appId": application_id, "dependencyId": None,
        "requirementCode": requirement_code, "citizenId": citizen_id, "sourceType": "CITIZEN_UPLOAD",
        "providerId": None, "documentType": requirement_code, "status": "VALIDATED",
        "checksum": checksum, "isSynthetic": True, "referenceUri": None,
        "validation": {"valid": True, "reasons": []}, "canonical": canonical,
        "title": body.title, "contentType": body.contentType,
        **({"contentPreview": body.content[:2000]} if not is_file else file_fields),
    })
    audit_bus.append(
        citizen_id, requirement_code, "Citizen uploaded a document manually", "Citizen Upload", "UPLOAD",
        payload={"appId": application_id, "requirementCode": requirement_code, "documentId": document_id, "actorRole": user["role"]},
        correlation_id=application_id,
    )
    _notify_requirement_outcome(citizen_id, application_id, requirement_code, label, previous_status, "VALIDATED")
    return _safe_application(application)


@router.delete("/applications/{application_id}/requirements/{requirement_code}/upload")
def remove_requirement_upload(application_id: str, requirement_code: str, user: dict = Depends(require_roles("CITIZEN"))):
    """Withdraw the citizen's own manual upload before submission: the
    requirement returns to NOT_PROVIDED (Auto-Fill and upload are available
    again) and the uploaded document reference is removed. Only a document
    the citizen uploaded can be removed -- never a verified provider result
    -- and never after the application has been submitted."""
    citizen_id = user["citizenId"]
    enforce("requirement_upload", citizen_id, limit=10, window_seconds=60)
    app = _load_owned_application(application_id, citizen_id)
    _assert_application_not_submitted(app)
    requirement = requirement_fulfillment.find_requirement(app, requirement_code)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found on this application")
    document_id = requirement.get("documentId")
    document = get_document(document_id) if document_id else None
    if not document or document.get("sourceType") != "CITIZEN_UPLOAD" or document.get("citizenId") != citizen_id:
        raise HTTPException(status_code=409, detail="There is no uploaded document to remove for this requirement.")

    def mutate(target: dict) -> None:
        target["status"] = "NOT_PROVIDED"
        target.pop("documentId", None)

    try:
        # The requirement reset and the document delete commit together (or
        # not at all), so they can never disagree.
        application, _ = requirement_fulfillment.mutate_requirement_under_lock(
            application_id, requirement_code, mutate, before_commit=lambda session: delete_document(document_id, session=session))
    except requirement_fulfillment.ApplicationSubmittedError:
        raise HTTPException(status_code=409, detail="This application has already been submitted and can no longer be changed.")
    audit_bus.append(
        citizen_id, requirement_code, "Citizen removed an uploaded document before submission", "Citizen Upload", "UPLOAD_REMOVED",
        payload={"appId": application_id, "requirementCode": requirement_code, "documentId": document_id, "actorRole": user["role"]},
        correlation_id=application_id,
    )
    return _safe_application(application)


def _owned_validated_document(application_id: str, requirement_code: str, citizen_id: str, include_file: bool = False) -> tuple[dict, dict]:
    """Shared ownership + status check for both the view and download
    routes: the application must belong to the caller, the requirement must
    exist on it, and only an already-VALIDATED document is ever exposed --
    never a provider/department/API/database detail, and never a
    still-pending or rejected result."""
    app = _load_owned_application(application_id, citizen_id)
    requirement = requirement_fulfillment.find_requirement(app, requirement_code)
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found on this application")
    document_id = requirement.get("documentId") or f"DOC-{application_id}-{requirement_code}"
    document = get_document(document_id, include_file=include_file)
    if not document or document.get("appId") != application_id or document.get("citizenId") != citizen_id or document.get("status") != "VALIDATED":
        raise HTTPException(status_code=404, detail="No verified document is available for this requirement")
    return requirement, document


def _document_view_payload(requirement: dict, document: dict, user: dict) -> dict:
    label = requirement.get("label") or str(requirement.get("code", "")).replace("_", " ").title()
    title = document_display_name(label)
    document_id = document["documentId"]
    if document.get("sizeBytes") is not None:
        # An uploaded image/PDF: the client previews the file itself
        # (fetched through the download route); only its metadata here.
        return {
            "documentId": document_id, "title": title, "requirementCode": requirement["code"], "status": document["status"],
            "isFile": True, "contentType": document.get("contentType"), "fileName": document.get("fileName"),
            "sizeBytes": document.get("sizeBytes"), "sourceType": "CITIZEN_UPLOAD",
        }
    if document.get("sourceType") == "CITIZEN_UPLOAD" and document.get("contentPreview"):
        # A citizen's own manual upload has no provider canonical fields to
        # show -- render back what they actually submitted instead.
        display_fields = {"Details": document["contentPreview"]}
    else:
        display_fields = document.get("canonical") or {}
    text = citizen_safe_document_text(
        title=title, reference=document_id, citizen_name=user.get("name"),
        canonical=display_fields, verified_on=requirement.get("verifiedOn"),
    )
    return {
        "documentId": document_id, "title": title, "requirementCode": requirement["code"],
        "status": document["status"], "content": text,
    }


@router.get("/applications/{application_id}/requirements/{requirement_code}/document")
def view_requirement_document(application_id: str, requirement_code: str, user: dict = Depends(require_roles("CITIZEN"))):
    """Citizen-facing verified-document view (Phase 6F2 Task C).

    Exposes only a citizen-safe rendering of an already-VALIDATED document
    reference -- title and canonical field values only, never the provider,
    department, API or database details behind it."""
    citizen_id = user["citizenId"]
    requirement, document = _owned_validated_document(application_id, requirement_code, citizen_id)
    return _document_view_payload(requirement, document, user)


@router.get("/applications/{application_id}/requirements/{requirement_code}/document/download")
def download_requirement_document(application_id: str, requirement_code: str, user: dict = Depends(require_roles("CITIZEN"))):
    """Download variant of the same citizen-safe document view: the original
    file for an uploaded image/PDF, otherwise a plain text rendering."""
    citizen_id = user["citizenId"]
    requirement, document = _owned_validated_document(application_id, requirement_code, citizen_id, include_file=True)
    if document.get("fileContent"):
        file_bytes = decode_upload_file(document["fileContent"]) or b""
        file_name = safe_upload_filename(document.get("fileName"), document.get("contentType", ""))
        return Response(content=file_bytes, media_type=document.get("contentType"),
                        headers={"Content-Disposition": 'attachment; filename="' + file_name + '"'})
    payload = _document_view_payload(requirement, document, user)
    filename = re.sub(r"[^A-Za-z0-9]+", "-", payload["title"]).strip("-") + ".txt"
    return Response(
        content=payload["content"], media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/applications/{application_id}/submit")
def submit_citizen_application(application_id: str, user: dict = Depends(require_roles("CITIZEN"))):
    """Application-level Review -> Submit (Phase 6E).

    Citizen identity comes only from the authenticated JWT -- there is no
    request body, so there is nothing for the client to spoof. Ownership,
    existence, and readiness are all re-verified against the authoritative
    PostgreSQL row under one row lock (app.engine.submission.
    submit_application), the same lock every requirement mutation already
    uses, so a requirement finishing (or being manually uploaded) at the
    exact moment of submission cannot be missed, and two concurrent submit
    requests cannot both produce an independent submission event -- the
    second one observes the first's committed SUBMITTED status and returns
    it unchanged rather than re-transitioning or duplicating any side
    effect. Once SUBMITTED, this application's requirements can no longer be
    mutated through Auto-Fill or manual upload (see
    requirement_fulfillment.ApplicationSubmittedError).
    """
    citizen_id = user["citizenId"]
    enforce("application_submit", citizen_id, limit=10, window_seconds=60)
    already_submitted = (get_application(application_id) or {}).get("status") == "SUBMITTED"
    try:
        application = submission.submit_application(application_id, citizen_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")
    except PermissionError:
        raise HTTPException(status_code=404, detail="Application not found")
    except submission.ApplicationNotSubmittableError:
        raise HTTPException(status_code=409, detail="This application cannot be submitted in its current state.")
    except submission.SubmissionNotReadyError as error:
        safe_app = _safe_application(_load_owned_application(application_id, citizen_id))
        raise HTTPException(status_code=422, detail={
            "message": "This application is not ready to submit yet.",
            "blockingRequirements": safe_app["blockingRequirements"],
        })
    audit_bus.append(
        citizen_id, "APPLICATION", "Citizen submitted application", "GovOrchestrator", "SUBMIT",
        payload={"appId": application_id, "actorRole": user["role"]}, correlation_id=application_id,
    )
    event_bus.publish("APPLICATION_SUBMITTED", {"citizenId": citizen_id, "appId": application_id})
    if not already_submitted:
        scheme_name = application.get("schemeName") or "your scheme"
        create_citizen_notification(
            citizen_id, "APPLICATION_SUBMITTED", "Application submitted",
            f"Your application for {scheme_name} was submitted successfully.", application_id=application_id,
        )
    return _safe_application(application)


@router.post("/orchestrate-dependency")
def dependency(body: Dependency, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    if not app or app["citizenId"] != body.citizenId:
        raise HTTPException(404, "Application journey not found")
    consent_receipt = _require_consent(body.citizenId, service_id=app.get("serviceId"), application_id=app.get("appId"))
    requirement_code = body.requirementCode or next((item["code"] for item in app.get("requirements", []) if item.get("status") in {"MISSING", "UNRESOLVED"}), None)
    if not requirement_code:
        raise HTTPException(status_code=400, detail="No unresolved configured requirement is available.")
    result = initiate_dependency(body.citizenId, app, requirement_code)
    if result.get("success"):
        audit_bus.append(body.citizenId, requirement_code, "Configured service dependency completed", "Configured provider", "ISSUE", consent_receipt["consentId"], payload={**result, "actorRole": user["role"]}, correlation_id=app["appId"])
    else:
        audit_bus.append(body.citizenId, requirement_code, "Configured service dependency failed; retry remains available", "Configured provider", "FAIL", consent_receipt["consentId"], payload={"dependencyId": result.get("dependencyId"), "attempts": result.get("attempts"), "status": result.get("dependencyStatus"), "actorRole": user["role"]}, correlation_id=app["appId"])
    return result


@router.post("/document-upload")
def document_upload(body: DocumentUpload, user: dict = Depends(require_roles("CITIZEN"))):
    """Backend/API boundary for a future citizen upload UI. Validates the
    artifact, then updates the requirement's dependency through the existing
    dependency mutation architecture (never a second state machine)."""
    _assert_own_citizen(user, body.citizenId)
    enforce("document_upload", body.citizenId, limit=10, window_seconds=60)
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    if not app or app["citizenId"] != body.citizenId:
        raise HTTPException(404, "Application journey not found")
    from app.engine.artifact_retrieval import submit_citizen_upload
    try:
        result = submit_citizen_upload(
            app, body.requirementCode, body.citizenId,
            {"title": body.title, "contentType": body.contentType, "content": body.content},
        )
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=403, detail=f"Protected access denied: {error}")
    audit_bus.append(body.citizenId, body.requirementCode, "Citizen document upload processed", "Citizen Upload",
                      result["status"], app.get("consentId"),
                      payload={"requirementCode": body.requirementCode, "status": result["status"], "actorRole": user["role"]},
                      correlation_id=app["appId"])
    return result


@router.post("/consent")
def consent(body: Consent, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    enforce("consent", body.citizenId, limit=10, window_seconds=60)
    citizen = user if user.get("citizenId") == body.citizenId else None
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    try:
        receipt = create_consent(body.citizenId, body.allow, body.attributes, service_id=body.schemeId, purpose=body.purpose)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    app = None
    if body.allow:
        result = discover({k: v for k, v in citizen.items() if k != "password"}, scheme_id=body.schemeId)
        app = find_active_application(body.citizenId) or create_application(body.citizenId, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        app["consentAttributes"] = list(receipt.get("allowed", []))
        receipt["applicationId"] = app["appId"]
        receipt["serviceId"] = app.get("serviceId") or body.schemeId
        _record_discovery(body.citizenId, result, app["appId"])
        _record_entity_reviews(app)
        dependency_records = ensure_missing_dependencies(app)
        dependency_record = dependency_records[0] if dependency_records else None
        receipt = {**receipt, "appId": app["appId"], "applicationStatus": app["status"], "dependencyId": dependency_record["dependencyId"] if dependency_record else None}
        event_bus.publish("CONSENT_GRANTED", {"citizenId": body.citizenId, "appId": app["appId"], "consentId": receipt["consentId"], "purpose": receipt["purpose"]})
    audit_bus.append(body.citizenId, "CONSENT", receipt["purpose"], receipt["consumer"], receipt["decision"], receipt["consentId"], {**receipt, "actorRole": user["role"]}, correlation_id=app["appId"] if app else None)
    return _safe_consent(receipt)


@router.post("/consent/revoke")
def revoke(body: RevokeConsent, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    try:
        receipt = revoke_consent(body.citizenId, body.consentId)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=404, detail=str(error))
    app = find_active_application(body.citizenId)
    correlation_id = app["appId"] if app else None
    event_bus.publish("CONSENT_REVOKED", {"citizenId": body.citizenId, "appId": correlation_id, "consentId": body.consentId})
    audit_bus.append(body.citizenId, "CONSENT", "Citizen revoked service data consent", CONSUMER, "REVOKE", body.consentId, payload={"consentId": body.consentId, "actorRole": user["role"]}, correlation_id=correlation_id)
    return _safe_consent(receipt)


@router.post("/submit")
def submit(body: Submit, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    citizen = user if user.get("citizenId") == body.citizenId else None
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    service_id = app.get("serviceId") if app else None
    existing_consent = current(body.citizenId) or {}
    consent_receipt = _require_consent(body.citizenId, existing_consent.get("purpose", PURPOSE), existing_consent.get("allowed", PERMITTED), service_id=service_id, application_id=app.get("appId") if app else None)
    result = discover({k: v for k, v in citizen.items() if k != "password"}, body.simulateTimeout, service_id=service_id)
    eligibility = evaluate(result["requirements"])
    app = app if app and app["citizenId"] == body.citizenId else create_application(body.citizenId, result, eligibility, service_id)
    app["consentId"] = consent_receipt["consentId"]
    app["consentAttributes"] = list(consent_receipt.get("allowed", []))
    app["requirements"] = result["requirements"]
    app["eligibility"] = eligibility
    _record_discovery(body.citizenId, result, app["appId"])
    _record_entity_reviews(app)
    missing_requirements = any(item.get("status") != "FOUND" for item in result["requirements"])
    if missing_requirements:
        ensure_missing_dependencies(app)
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    elif not eligibility["eligible"]:
        transition_application(app, "VERIFICATION_FAILED")
    else:
        transition_application(app, "IN_PROGRESS")
        transition_application(app, "SUBMITTED")
        transition_application(app, "WAITING_FOR_OFFICER")
    event_bus.publish("APPLICATION_SUBMITTED", {"citizenId": body.citizenId, "appId": app["appId"], "consentId": consent_receipt["consentId"]})
    audit_bus.append(body.citizenId, "APPLICATION", "Configured service application submission", "GovOrchestrator", "SUBMIT", consent_receipt["consentId"], payload={"appId": app["appId"], "serviceId": app.get("serviceId"), "eligible": eligibility["eligible"], "actorRole": user["role"]}, correlation_id=app["appId"])
    return _safe_application(app)


@router.get("/track/{app_id}")
def track(app_id: str, user: dict = Depends(require_roles("CITIZEN", "OFFICER"))):
    app = APPLICATIONS.get(app_id)
    if not app:
        with Session(engine) as session:
            db_app = get_application(app_id, session=session)
            if db_app:
                app = _application_with_database_dependencies(db_app, session)
    if not app:
        raise HTTPException(404, "Application not found")
    if user.get("role") == "CITIZEN" and app.get("citizenId") != user.get("citizenId"):
        raise HTTPException(status_code=404, detail="Application not found")
    receipt = current(app.get("citizenId"))
    consent_view = None
    if receipt:
        consent_view = {field: receipt.get(field) for field in ("consentId", "serviceId", "purpose", "allowed", "expiresAt", "decision", "createdAt", "revokedAt") if field in receipt}
    workflow_events = _safe_workflow_events(event_bus.events, app_id)
    audit_entries = [{field: entry.get(field) for field in ("sequence", "what", "when", "action")} for entry in audit_bus.entries if entry.get("correlationId") == app_id]
    return {**_safe_application(app), "consent": {field: consent_view.get(field) for field in ("consentId", "serviceId", "purpose", "allowed", "decision", "createdAt", "expiresAt", "revokedAt") if consent_view and field in consent_view} if consent_view else None, "workflowEvents": workflow_events, "auditEntries": audit_entries}
