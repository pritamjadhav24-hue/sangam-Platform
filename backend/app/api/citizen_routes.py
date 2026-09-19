from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.audit_bus import audit_bus
from app.core.auth import require_roles
from app.core.event_bus import event_bus
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent, current, revoke_consent
from app.engine.dependency_orchestrator import ensure_domicile_dependency, ensure_missing_dependencies, initiate_domicile
from app.core.persistence import catalog_snapshot
from app.engine.registry import SCHEMES
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import APPLICATIONS, create_application, find_active_application, transition_application

router = APIRouter(prefix="/api/citizen", tags=["Citizen"])


class Consent(BaseModel):
    citizenId: str
    allow: bool
    attributes: Optional[List[str]] = None
    schemeId: Optional[str] = None


class Dependency(BaseModel):
    citizenId: str
    appId: Optional[str] = None


class Submit(BaseModel):
    citizenId: str
    appId: Optional[str] = None
    simulateTimeout: bool = False


class RevokeConsent(BaseModel):
    citizenId: str
    consentId: str


def _record_discovery(citizen_id: str, result: dict, app_id: Optional[str] = None) -> None:
    for item in result["requirements"]:
        audit_bus.append(citizen_id, item["code"], "Scholarship requirement discovery", item["source"], "PROBE", payload=item.get("canonical", {}), correlation_id=app_id)
        if item["status"] == "FOUND":
            event_bus.publish(f"{item['code']}_VERIFIED", {"citizenId": citizen_id, "appId": app_id, "requirement": item["code"]})


def _record_entity_reviews(app: dict) -> None:
    for review in app.get("entityReviews", []):
        if review.get("auditRecorded"):
            continue
        audit_bus.append(app["citizenId"], "ENTITY_RESOLUTION", "Medium-confidence cross-system match requires human review", review["source"], "REVIEW_REQUIRED", app.get("consentId"), payload={"reviewId": review["reviewId"], "appId": app["appId"], "requirementCode": review["requirementCode"], "sourceRecordId": review["sourceRecordId"], "confidenceScore": review["confidenceScore"], "confidenceLevel": review["confidenceLevel"]}, correlation_id=app["appId"])
        review["auditRecorded"] = True


def _require_consent(citizen_id: str, purpose: str = PURPOSE, attributes: Optional[List[str]] = None) -> dict:
    try:
        return authorize_access(citizen_id, CONSUMER, purpose, attributes)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=403, detail=f"Protected access denied: {error}")


def _assert_own_citizen(user: dict, citizen_id: str) -> None:
    if user.get("role") != "CITIZEN" or user.get("citizenId") != citizen_id:
        raise HTTPException(status_code=403, detail="Citizens may access only their own services.")


@router.get("/schemes")
def schemes(user: dict = Depends(require_roles("CITIZEN"))):
    configured = catalog_snapshot()["schemes"]
    return {"schemes": configured or SCHEMES}


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
    return result


@router.post("/orchestrate-dependency")
def dependency(body: Dependency, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    if not app or app["citizenId"] != body.citizenId:
        raise HTTPException(404, "Application journey not found")
    consent_receipt = _require_consent(body.citizenId)
    result = initiate_domicile(body.citizenId, app)
    if result.get("success"):
        audit_bus.append(body.citizenId, "DOMICILE_PROOF", "Mandatory scholarship prerequisite", "Revenue Department", "ISSUE", consent_receipt["consentId"], payload={**result, "actorRole": user["role"]}, correlation_id=app["appId"])
    else:
        audit_bus.append(body.citizenId, "DOMICILE_PROOF", "Mandatory scholarship prerequisite failed; retry remains available", "Revenue Department", "FAIL", consent_receipt["consentId"], payload={"dependencyId": result.get("dependencyId"), "attempts": result.get("attempts"), "status": result.get("dependencyStatus"), "actorRole": user["role"]}, correlation_id=app["appId"])
    return result


@router.post("/consent")
def consent(body: Consent, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    citizen = user if user.get("citizenId") == body.citizenId else None
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    try:
        receipt = create_consent(body.citizenId, body.allow, body.attributes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    app = None
    if body.allow:
        result = discover({k: v for k, v in citizen.items() if k != "password"}, scheme_id=body.schemeId)
        app = find_active_application(body.citizenId) or create_application(body.citizenId, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        _record_discovery(body.citizenId, result, app["appId"])
        _record_entity_reviews(app)
        dependency_records = ensure_missing_dependencies(app)
        dependency_record = dependency_records[0] if dependency_records else None
        receipt = {**receipt, "appId": app["appId"], "applicationStatus": app["status"], "dependencyId": dependency_record["dependencyId"] if dependency_record else None}
        event_bus.publish("CONSENT_GRANTED", {"citizenId": body.citizenId, "appId": app["appId"], "consentId": receipt["consentId"], "purpose": receipt["purpose"]})
    audit_bus.append(body.citizenId, "CONSENT", receipt["purpose"], receipt["consumer"], receipt["decision"], receipt["consentId"], {**receipt, "actorRole": user["role"]}, correlation_id=app["appId"] if app else None)
    return receipt


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
    audit_bus.append(body.citizenId, "CONSENT", "Citizen revoked scholarship data consent", CONSUMER, "REVOKE", body.consentId, payload={"consentId": body.consentId, "actorRole": user["role"]}, correlation_id=correlation_id)
    return receipt


@router.post("/submit")
def submit(body: Submit, user: dict = Depends(require_roles("CITIZEN"))):
    _assert_own_citizen(user, body.citizenId)
    citizen = user if user.get("citizenId") == body.citizenId else None
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    consent_receipt = _require_consent(body.citizenId, PURPOSE, PERMITTED)
    result = discover({k: v for k, v in citizen.items() if k != "password"}, body.simulateTimeout, app.get("schemeId") if app else None)
    eligibility = evaluate(result["requirements"])
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    app = app if app and app["citizenId"] == body.citizenId else create_application(body.citizenId, result, eligibility)
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
    audit_bus.append(body.citizenId, "APPLICATION", "Scholarship application assembly", "GovOrchestrator", "SUBMIT", consent_receipt["consentId"], payload={"appId": app["appId"], "eligible": eligibility["eligible"], "actorRole": user["role"]}, correlation_id=app["appId"])
    return app


@router.get("/track/{app_id}")
def track(app_id: str, user: dict = Depends(require_roles("CITIZEN", "OFFICER"))):
    if app_id not in APPLICATIONS:
        raise HTTPException(404, "Application not found")
    app = APPLICATIONS[app_id]
    if user.get("role") == "CITIZEN" and app["citizenId"] != user.get("citizenId"):
        raise HTTPException(status_code=403, detail="Citizens may track only their own applications.")
    receipt = current(app["citizenId"])
    consent_view = None
    if receipt:
        consent_view = {field: receipt.get(field) for field in ("consentId", "consumer", "purpose", "allowed", "expiresAt", "decision", "revokedAt") if field in receipt}
    workflow_events = [event for event in event_bus.events if event.get("payload", {}).get("appId") == app_id]
    audit_entries = [{field: entry.get(field) for field in ("sequence", "what", "why", "when", "source", "action", "consentId", "correlationId")} for entry in audit_bus.entries if entry.get("correlationId") == app_id]
    return {**app, "consent": consent_view, "workflowEvents": workflow_events, "auditEntries": audit_entries}
