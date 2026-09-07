import itertools
from datetime import datetime, timezone

APPLICATIONS: dict[str, dict] = {}
_counter = itertools.count(142)
STAGES = ["Submitted", "Identity", "Income", "Academic", "Domicile", "Officer Review", "Completed"]


def create_application(citizen_id: str, discovery: dict, eligibility: dict) -> dict:
    app_id = f"SCH-MH-2026-{next(_counter):05d}"
    requirement_map = {r["code"]: r for r in discovery["requirements"]}
    timeline = []
    for stage in STAGES:
        lookup = {"Identity": "IDENTITY", "Income": "INCOME_PROOF", "Academic": "ACADEMIC_RECORD", "Domicile": "DOMICILE_PROOF"}.get(stage)
        state = "COMPLETED" if stage == "Submitted" or (lookup and requirement_map.get(lookup, {}).get("status") == "FOUND") else "PENDING"
        if stage == "Officer Review": state = "PENDING" if eligibility["eligible"] else "BLOCKED"
        if stage == "Completed": state = "PENDING" if eligibility["eligible"] else "BLOCKED"
        timeline.append({"stage": stage, "state": state, "at": datetime.now(timezone.utc).isoformat() if state == "COMPLETED" else None})
    app = {"appId": app_id, "citizenId": citizen_id, "status": "UNDER_OFFICER_REVIEW" if eligibility["eligible"] else "INELIGIBLE", "createdAt": datetime.now(timezone.utc).isoformat(), "requirements": discovery["requirements"], "eligibility": eligibility, "timeline": timeline, "officerRemarks": None}
    APPLICATIONS[app_id] = app
    return app


def officer_action(app_id: str, action: str, remarks: str):
    app = APPLICATIONS.get(app_id)
    if not app: return None
    if action not in {"APPROVE", "REJECT", "REQUEST_INFO"} or not remarks.strip(): raise ValueError("A decision and mandatory remarks are required.")
    app["officerRemarks"] = remarks
    app["status"] = {"APPROVE": "COMPLETED", "REJECT": "REJECTED", "REQUEST_INFO": "RESUBMISSION_REQUIRED"}[action]
    for item in app["timeline"]:
        if item["stage"] == "Officer Review": item["state"] = "COMPLETED" if action == "APPROVE" else "EXCEPTION"
        if item["stage"] == "Completed" and action == "APPROVE": item["state"], item["at"] = "COMPLETED", datetime.now(timezone.utc).isoformat()
    return app
