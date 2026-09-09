from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.consent_manager import CONSUMER, PERMITTED, PURPOSE, ConsentAuthorizationError, authorize_access, create_consent, revoke_consent
from app.engine.dependency_orchestrator import ensure_domicile_dependency, initiate_domicile
from app.engine.registry import SCHEMES
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import APPLICATIONS, create_application, find_active_application, transition_application
from app.mocks.identity_provider import CITIZENS

router = APIRouter(prefix="/api/citizen", tags=["Citizen"])


class Consent(BaseModel):
    citizenId: str
    allow: bool
    attributes: Optional[List[str]] = None


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


def _require_consent(citizen_id: str, purpose: str = PURPOSE, attributes: Optional[List[str]] = None) -> dict:
    try:
        return authorize_access(citizen_id, CONSUMER, purpose, attributes)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=403, detail=f"Protected access denied: {error}")


@router.get("/schemes")
def schemes():
    return {"schemes": SCHEMES}


@router.get("/discover")
def discovery(citizen_id: str = "CITIZEN_001", simulate_timeout: bool = False, purpose: Optional[str] = None, attributes: Optional[List[str]] = None):
    citizen = CITIZENS.get(citizen_id)
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    if purpose is not None or attributes:
        if not purpose:
            raise HTTPException(status_code=403, detail="Protected access denied: a purpose is required.")
        _require_consent(citizen_id, purpose, attributes)
    result = discover({k: v for k, v in citizen.items() if k != "password"}, simulate_timeout)
    app = find_active_application(citizen_id)
    _record_discovery(citizen_id, result, app["appId"] if app else None)
    return result


@router.post("/orchestrate-dependency")
def dependency(body: Dependency):
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    if not app or app["citizenId"] != body.citizenId:
        raise HTTPException(404, "Application journey not found")
    consent_receipt = _require_consent(body.citizenId)
    result = initiate_domicile(body.citizenId, app)
    audit_bus.append(body.citizenId, "DEPENDENCY", "Mandatory scholarship prerequisite", "GovOrchestrator", "CREATED", consent_receipt["consentId"], payload={"dependencyId": result.get("dependencyId"), "appId": app["appId"]}, correlation_id=app["appId"])
    audit_bus.append(body.citizenId, "DOMICILE_PROOF", "Mandatory scholarship prerequisite", "Revenue Department", "ISSUE", consent_receipt["consentId"], payload=result, correlation_id=app["appId"])
    return result


@router.post("/consent")
def consent(body: Consent):
    citizen = CITIZENS.get(body.citizenId)
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    try:
        receipt = create_consent(body.citizenId, body.allow, body.attributes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    app = None
    if body.allow:
        result = discover({k: v for k, v in citizen.items() if k != "password"})
        app = find_active_application(body.citizenId) or create_application(body.citizenId, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        _record_discovery(body.citizenId, result, app["appId"])
        dependency_record = ensure_domicile_dependency(app) if any(item["code"] == "DOMICILE_PROOF" and item["status"] != "FOUND" for item in result["requirements"]) else None
        receipt = {**receipt, "appId": app["appId"], "applicationStatus": app["status"], "dependencyId": dependency_record["dependencyId"] if dependency_record else None}
        event_bus.publish("CONSENT_GRANTED", {"citizenId": body.citizenId, "appId": app["appId"], "consentId": receipt["consentId"], "purpose": receipt["purpose"]})
    audit_bus.append(body.citizenId, "CONSENT", receipt["purpose"], receipt["consumer"], receipt["decision"], receipt["consentId"], receipt, correlation_id=app["appId"] if app else None)
    return receipt


@router.post("/consent/revoke")
def revoke(body: RevokeConsent):
    try:
        receipt = revoke_consent(body.citizenId, body.consentId)
    except ConsentAuthorizationError as error:
        raise HTTPException(status_code=404, detail=str(error))
    app = find_active_application(body.citizenId)
    correlation_id = app["appId"] if app else None
    event_bus.publish("CONSENT_REVOKED", {"citizenId": body.citizenId, "appId": correlation_id, "consentId": body.consentId})
    audit_bus.append(body.citizenId, "CONSENT", "Citizen revoked scholarship data consent", CONSUMER, "REVOKE", body.consentId, payload={"consentId": body.consentId}, correlation_id=correlation_id)
    return receipt


@router.post("/submit")
def submit(body: Submit):
    citizen = CITIZENS.get(body.citizenId)
    if not citizen:
        raise HTTPException(404, "Citizen not found")
    consent_receipt = _require_consent(body.citizenId, PURPOSE, PERMITTED)
    result = discover({k: v for k, v in citizen.items() if k != "password"}, body.simulateTimeout)
    eligibility = evaluate(result["requirements"])
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    app = app if app and app["citizenId"] == body.citizenId else create_application(body.citizenId, result, eligibility)
    app["requirements"] = result["requirements"]
    app["eligibility"] = eligibility
    _record_discovery(body.citizenId, result, app["appId"])
    missing_domicile = any(item["code"] == "DOMICILE_PROOF" and item["status"] != "FOUND" for item in result["requirements"])
    if missing_domicile:
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    elif not eligibility["eligible"]:
        transition_application(app, "VERIFICATION_FAILED")
    else:
        transition_application(app, "IN_PROGRESS")
        transition_application(app, "SUBMITTED")
        transition_application(app, "WAITING_FOR_OFFICER")
    event_bus.publish("APPLICATION_SUBMITTED", {"citizenId": body.citizenId, "appId": app["appId"], "consentId": consent_receipt["consentId"]})
    audit_bus.append(body.citizenId, "APPLICATION", "Scholarship application assembly", "GovOrchestrator", "SUBMIT", consent_receipt["consentId"], payload={"appId": app["appId"], "eligible": eligibility["eligible"]}, correlation_id=app["appId"])
    return app


@router.get("/track/{app_id}")
def track(app_id: str):
    if app_id not in APPLICATIONS:
        raise HTTPException(404, "Application not found")
    return APPLICATIONS[app_id]
