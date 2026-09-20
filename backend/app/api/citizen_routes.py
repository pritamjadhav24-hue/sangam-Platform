from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit_bus import audit_bus
from app.core.auth import require_roles
from app.core.event_bus import event_bus
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent, current, revoke_consent
from app.engine.dependency_orchestrator import ensure_missing_dependencies, initiate_dependency
from app.core.persistence import (citizen_service_snapshot, catalog_snapshot, engine,
                                  get_application, list_applications_for_citizen,
                                  list_dependencies_for_application)
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


class ApplicationCreate(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    serviceId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    purpose: Optional[str] = Field(default=None, max_length=240)
    attributes: Optional[List[str]] = None


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


def _safe_application(app: dict) -> dict:
    safe_requirements = []
    for requirement in app.get("requirements", []):
        safe_requirements.append({
            "requirementCode": requirement.get("code"),
            "displayLabel": requirement.get("label") or str(requirement.get("code", "")).replace("_", " ").title(),
            "status": requirement.get("status"),
            "userAction": requirement.get("action") or ("No action required" if requirement.get("status") == "FOUND" else "Retry verification or request help"),
            **({"verifiedOn": requirement.get("verifiedOn")} if requirement.get("verifiedOn") else {}),
        })
    safe_conflicts = [{"status": item.get("status"), "field": item.get("canonicalField"), "message": "Additional review is required."} for item in app.get("conflicts", [])]
    safe_dependencies = []
    for dependency_item in app.get("dependencies", []):
        safe_dependencies.append({field: dependency_item.get(field) for field in ("requiredService", "serviceName", "status", "attempts", "maxAttempts") if field in dependency_item})
    safe = {field: app.get(field) for field in ("appId", "serviceId", "schemeId", "status", "consentId", "createdAt", "updatedAt") if field in app}
    safe["citizenId"] = None
    safe["requirements"] = safe_requirements
    safe["conflicts"] = safe_conflicts
    safe["entityReviews"] = []
    safe["conflictReviews"] = []
    safe["dependencies"] = safe_dependencies
    if isinstance(app.get("eligibility"), dict):
        safe["eligibility"] = {field: app["eligibility"].get(field) for field in ("eligible", "reasons") if field in app["eligibility"]}
    if isinstance(app.get("statusHistory"), list):
        safe["statusHistory"] = [{field: item.get(field) for field in ("status", "at") if field in item} for item in app["statusHistory"]]
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


@router.get("/applications")
def list_citizen_applications(user: dict = Depends(require_roles("CITIZEN"))):
    with Session(engine) as session:
        applications = list_applications_for_citizen(user.get("citizenId"), session=session)
        return {"applications": [_safe_application(_application_with_database_dependencies(app, session)) for app in applications]}


@router.get("/applications/{application_id}")
def get_citizen_application(application_id: str, user: dict = Depends(require_roles("CITIZEN"))):
    with Session(engine) as session:
        app = get_application(application_id, session=session)
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app.get("citizenId") != user.get("citizenId"):
            raise HTTPException(status_code=404, detail="Application not found")
        return _safe_application(_application_with_database_dependencies(app, session))


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
    if app_id not in APPLICATIONS:
        raise HTTPException(404, "Application not found")
    app = APPLICATIONS[app_id]
    if user.get("role") == "CITIZEN" and app["citizenId"] != user.get("citizenId"):
        raise HTTPException(status_code=404, detail="Application not found")
    receipt = current(app["citizenId"])
    consent_view = None
    if receipt:
        consent_view = {field: receipt.get(field) for field in ("consentId", "serviceId", "purpose", "allowed", "expiresAt", "decision", "createdAt", "revokedAt") if field in receipt}
    workflow_events = _safe_workflow_events(event_bus.events, app_id)
    audit_entries = [{field: entry.get(field) for field in ("sequence", "what", "when", "action")} for entry in audit_bus.entries if entry.get("correlationId") == app_id]
    return {**_safe_application(app), "consent": {field: consent_view.get(field) for field in ("consentId", "serviceId", "purpose", "allowed", "decision", "createdAt", "expiresAt", "revokedAt") if consent_view and field in consent_view} if consent_view else None, "workflowEvents": workflow_events, "auditEntries": audit_entries}
