from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.consent_manager import create_consent
from app.engine.dependency_orchestrator import initiate_domicile
from app.engine.registry import SCHEMES
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import APPLICATIONS, create_application
from app.mocks.identity_provider import CITIZENS

router = APIRouter(prefix="/api/citizen", tags=["Citizen"])
class Consent(BaseModel): citizenId: str; allow: bool; attributes: list[str] | None = None
class Dependency(BaseModel): citizenId: str
class Submit(BaseModel): citizenId: str; simulateTimeout: bool = False
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
    result = initiate_domicile(body.citizenId)
    audit_bus.append(body.citizenId, "DOMICILE_PROOF", "Mandatory scholarship prerequisite", "Revenue Department", "ISSUE", payload=result)
    return result
@router.post("/consent")
def consent(body: Consent):
    receipt = create_consent(body.citizenId, body.allow, body.attributes)
    audit_bus.append(body.citizenId, "CONSENT", receipt["purpose"], receipt["consumer"], receipt["decision"], receipt["consentId"], receipt)
    return receipt
@router.post("/submit")
def submit(body: Submit):
    citizen = CITIZENS.get(body.citizenId)
    if not citizen: raise HTTPException(404, "Citizen not found")
    result = discover({k:v for k,v in citizen.items() if k != "password"}, body.simulateTimeout)
    eligibility = evaluate(result["requirements"])
    app = create_application(body.citizenId, result, eligibility)
    audit_bus.append(body.citizenId, "APPLICATION", "Scholarship application assembly", "GovOrchestrator", "SUBMIT", payload={"appId": app["appId"], "eligible": eligibility["eligible"]})
    return app
@router.get("/track/{app_id}")
def track(app_id: str):
    if app_id not in APPLICATIONS: raise HTTPException(404, "Application not found")
    return APPLICATIONS[app_id]
