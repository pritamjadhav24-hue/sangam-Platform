from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.workflow_engine import APPLICATIONS, CONFLICT_REVIEWS, conflict_review_action, entity_review_action, officer_action

router = APIRouter(prefix="/api/officer", tags=["Officer"])
class Action(BaseModel): appId: str; action: str; remarks: str; officerId: str = "OFFICER_MH_01"; reviewId: Optional[str] = None; selectedSource: Optional[str] = None
@router.get("/queue")
def queue():
    # Least privilege: personal identity/contact information is deliberately absent.
    apps = [a for a in APPLICATIONS.values() if a["status"] in {"WAITING_FOR_OFFICER", "WAITING_FOR_USER", "CONFLICT_DETECTED"}]
    return {"applications": [{"appId": a["appId"], "status": a["status"], "eligibility": a["eligibility"], "requirements": [{"code": r["code"], "status": r["status"], "canonical": r.get("canonical", {})} for r in a["requirements"]], "entityReviews": [{"reviewId": r["reviewId"], "appId": r["appId"], "requirementCode": r["requirementCode"], "source": r["source"], "sourceRecordId": r["sourceRecordId"], "confidenceScore": r["confidenceScore"], "confidenceLevel": r["confidenceLevel"], "matchedFields": r["matchedFields"], "status": r["status"], "decision": r["decision"]} for r in a.get("entityReviews", [])], "conflictReviews": [{"reviewId": r["reviewId"], "appId": r["appId"], "requirementCode": r["requirementCode"], "canonicalField": r["canonicalField"], "sources": r["sources"], "status": r["status"], "decision": r["decision"], "selectedSource": r.get("selectedSource"), "selectedValue": r.get("selectedValue")} for r in a.get("conflictReviews", [])]} for a in apps]}
@router.post("/action")
def action(body: Action):
    if body.reviewId:
        try:
            if body.reviewId in CONFLICT_REVIEWS:
                app, review = conflict_review_action(body.reviewId, body.action, body.officerId, body.remarks, body.selectedSource)
            else:
                app, review = entity_review_action(body.reviewId, body.action, body.officerId, body.remarks)
        except ValueError as error: raise HTTPException(400, str(error))
        if not app: raise HTTPException(404, "Entity review not found")
        event_bus.publish("OFFICER_ENTITY_REVIEW_ACTION" if body.reviewId not in CONFLICT_REVIEWS else "OFFICER_CONFLICT_REVIEW_ACTION", {"appId": app["appId"], "reviewId": body.reviewId, "consentId": app.get("consentId"), "officerId": body.officerId, "decision": body.action, "selectedSource": body.selectedSource})
        if body.reviewId in CONFLICT_REVIEWS:
            audit_bus.append(body.officerId, "CONFLICT_RESOLUTION", "Officer resolved conflicting canonical values", "Cross-system sources", body.action, app.get("consentId"), payload={"appId": app["appId"], "conflictId": body.reviewId, "canonicalField": review["canonicalField"], "selectedSource": body.selectedSource, "selectedValue": review.get("selectedValue")}, correlation_id=app["appId"])
        else:
            audit_bus.append(body.officerId, "ENTITY_RESOLUTION", "Officer decided a cross-system entity match", review["source"], body.action, app.get("consentId"), payload={"appId": app["appId"], "reviewId": body.reviewId, "requirementCode": review["requirementCode"], "confidenceLevel": review["confidenceLevel"]}, correlation_id=app["appId"])
        return app
    try: app = officer_action(body.appId, body.action, body.remarks)
    except ValueError as error: raise HTTPException(400, str(error))
    if not app: raise HTTPException(404, "Application not found")
    event_bus.publish("OFFICER_ACTION", {"appId": body.appId, "consentId": app.get("consentId"), "officerId": body.officerId, "action": body.action})
    audit_bus.append(body.officerId, "APPLICATION", "Officer workflow decision", "Higher Education Department", body.action, app.get("consentId"), payload={"appId": body.appId, "remarks": body.remarks}, correlation_id=body.appId)
    return app
