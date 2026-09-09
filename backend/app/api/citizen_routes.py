from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.consent_manager import create_consent
from app.engine.dependency_orchestrator import ensure_domicile_dependency, initiate_domicile
from app.engine.registry import SCHEMES
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import APPLICATIONS, create_application, find_active_application, transition_application
from app.mocks.identity_provider import CITIZENS

router = APIRouter(prefix="/api/citizen", tags=["Citizen"])
class Consent(BaseModel): citizenId: str; allow: bool; attributes: Optional[List[str]] = None
class Dependency(BaseModel): citizenId: str; appId: Optional[str] = None
class Submit(BaseModel): citizenId: str; appId: Optional[str] = None; simulateTimeout: bool = False
@router.get("/schemes")
def schemes(): return {"schemes": SCHEMES}
@router.get("/discover")
def discovery(citizen_id: str = "CITIZEN_001", simulate_timeout: bool = False):
    citizen = CITIZENS.get(citizen_id)
    if not citizen: raise HTTPException(404, "Citizen not found")
    result = discover({k:v for k,v in citizen.items() if k != "password"}, simulate_timeout)
    for item in result["requirements"]:
        audit_bus.append(citizen_id, item["code"], "Scholarship requirement discovery", item["source"], "PROBE", payload=item.get("canonical", {}))
        if item["status"] == "FOUND": event_bus.publish(f"{item['code']}_VERIFIED", {"citizenId": citizen_id})
    return result
@router.post("/orchestrate-dependency")
def dependency(body: Dependency):
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    if not app or app["citizenId"] != body.citizenId: raise HTTPException(404, "Application journey not found")
    result = initiate_domicile(body.citizenId, app)
    audit_bus.append(body.citizenId, "DOMICILE_PROOF", "Mandatory scholarship prerequisite", "Revenue Department", "ISSUE", payload=result)
    return result
@router.post("/consent")
def consent(body: Consent):
    citizen = CITIZENS.get(body.citizenId)
    if not citizen: raise HTTPException(404, "Citizen not found")
    receipt = create_consent(body.citizenId, body.allow, body.attributes)
    app = None
    if body.allow:
        result = discover({k:v for k, v in citizen.items() if k != "password"})
        app = find_active_application(body.citizenId) or create_application(body.citizenId, result, evaluate(result["requirements"]))
        app["consentId"] = receipt["consentId"]
        dependency_record = ensure_domicile_dependency(app) if any(item["code"] == "DOMICILE_PROOF" and item["status"] != "FOUND" for item in result["requirements"]) else None
        receipt = {**receipt, "appId": app["appId"], "applicationStatus": app["status"], "dependencyId": dependency_record["dependencyId"] if dependency_record else None}
    audit_bus.append(body.citizenId, "CONSENT", receipt["purpose"], receipt["consumer"], receipt["decision"], receipt["consentId"], receipt)
    return receipt
@router.post("/submit")
def submit(body: Submit):
    citizen = CITIZENS.get(body.citizenId)
    if not citizen: raise HTTPException(404, "Citizen not found")
    result = discover({k:v for k,v in citizen.items() if k != "password"}, body.simulateTimeout)
    eligibility = evaluate(result["requirements"])
    app = APPLICATIONS.get(body.appId) if body.appId else find_active_application(body.citizenId)
    app = app if app and app["citizenId"] == body.citizenId else create_application(body.citizenId, result, eligibility)
    app["requirements"] = result["requirements"]
    app["eligibility"] = eligibility
    missing_domicile = any(item["code"] == "DOMICILE_PROOF" and item["status"] != "FOUND" for item in result["requirements"])
    if missing_domicile:
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    elif not eligibility["eligible"]:
        transition_application(app, "VERIFICATION_FAILED")
    else:
        transition_application(app, "IN_PROGRESS")
        transition_application(app, "SUBMITTED")
        transition_application(app, "WAITING_FOR_OFFICER")
    audit_bus.append(body.citizenId, "APPLICATION", "Scholarship application assembly", "GovOrchestrator", "SUBMIT", payload={"appId": app["appId"], "eligible": eligibility["eligible"]})
    return app
@router.get("/track/{app_id}")
def track(app_id: str):
    if app_id not in APPLICATIONS: raise HTTPException(404, "Application not found")
    return APPLICATIONS[app_id]
