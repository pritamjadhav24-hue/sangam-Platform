from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.workflow_engine import APPLICATIONS, officer_action

router = APIRouter(prefix="/api/officer", tags=["Officer"])
class Action(BaseModel): appId: str; action: str; remarks: str; officerId: str = "OFFICER_MH_01"
@router.get("/queue")
def queue():
    # Least privilege: personal identity/contact information is deliberately absent.
    apps = [a for a in APPLICATIONS.values() if a["status"] in {"WAITING_FOR_OFFICER", "WAITING_FOR_USER"}]
    return {"applications": [{"appId": a["appId"], "status": a["status"], "eligibility": a["eligibility"], "requirements": [{"code": r["code"], "status": r["status"], "canonical": r.get("canonical", {})} for r in a["requirements"]]} for a in apps]}
@router.post("/action")
def action(body: Action):
    try: app = officer_action(body.appId, body.action, body.remarks)
    except ValueError as error: raise HTTPException(400, str(error))
    if not app: raise HTTPException(404, "Application not found")
    event_bus.publish("OFFICER_ACTION", {"appId": body.appId, "consentId": app.get("consentId"), "officerId": body.officerId, "action": body.action})
    audit_bus.append(body.officerId, "APPLICATION", "Officer workflow decision", "Higher Education Department", body.action, app.get("consentId"), payload={"appId": body.appId, "remarks": body.remarks}, correlation_id=body.appId)
    return app
