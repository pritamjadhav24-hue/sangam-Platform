from __future__ import annotations

import itertools
from datetime import datetime, timezone

APPLICATIONS: dict[str, dict] = {}
DEPENDENCIES: dict[str, dict] = {}
_counter = itertools.count(142)
STAGES = ["Submitted", "Identity", "Income", "Academic", "Domicile", "Officer Review", "Completed"]
CANONICAL_STATUSES = {
    "DRAFT", "SUBMITTED", "IN_PROGRESS", "WAITING_FOR_DEPENDENCY", "WAITING_FOR_USER",
    "WAITING_FOR_OFFICER", "VERIFICATION_FAILED", "CONFLICT_DETECTED", "APPROVED",
    "REJECTED", "COMPLETED", "CANCELLED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def transition_application(app: dict, status: str) -> dict:
    if status not in CANONICAL_STATUSES:
        raise ValueError(f"Unsupported application status: {status}")
    if app["status"] != status:
        timestamp = _now()
        app["status"] = status
        app["updatedAt"] = timestamp
        app.setdefault("statusHistory", []).append({"status": status, "at": timestamp})
    return app


def find_active_application(citizen_id: str) -> dict | None:
    terminal = {"COMPLETED", "REJECTED", "CANCELLED"}
    return next((app for app in reversed(list(APPLICATIONS.values()))
                 if app["citizenId"] == citizen_id and app["status"] not in terminal), None)


def create_application(citizen_id: str, discovery: dict, eligibility: dict) -> dict:
    app_id = f"SCH-MH-2026-{next(_counter):05d}"
    created_at = _now()
    requirement_map = {r["code"]: r for r in discovery["requirements"]}
    timeline = []
    for stage in STAGES:
        lookup = {"Identity": "IDENTITY", "Income": "INCOME_PROOF", "Academic": "ACADEMIC_RECORD", "Domicile": "DOMICILE_PROOF"}.get(stage)
        state = "COMPLETED" if lookup and requirement_map.get(lookup, {}).get("status") == "FOUND" else "PENDING"
        timeline.append({"stage": stage, "state": state, "at": created_at if state == "COMPLETED" else None})

    app = {
        "appId": app_id, "citizenId": citizen_id, "status": "DRAFT", "createdAt": created_at,
        "updatedAt": created_at, "requirements": discovery["requirements"], "eligibility": eligibility,
        "timeline": timeline, "statusHistory": [{"status": "DRAFT", "at": created_at}],
        "dependencyIds": [], "dependencies": [], "consentId": None, "officerRemarks": None,
    }
    APPLICATIONS[app_id] = app
    transition_application(app, "IN_PROGRESS")
    if requirement_map.get("DOMICILE_PROOF", {}).get("status") != "FOUND":
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    elif not eligibility["eligible"]:
        transition_application(app, "VERIFICATION_FAILED")
    return app


def officer_action(app_id: str, action: str, remarks: str):
    app = APPLICATIONS.get(app_id)
    if not app: return None
    if action not in {"APPROVE", "REJECT", "REQUEST_INFO"} or not remarks.strip(): raise ValueError("A decision and mandatory remarks are required.")
    app["officerRemarks"] = remarks
    if action == "APPROVE":
        transition_application(app, "APPROVED")
        transition_application(app, "COMPLETED")
    elif action == "REJECT":
        transition_application(app, "REJECTED")
    else:
        transition_application(app, "WAITING_FOR_USER")
    for item in app["timeline"]:
        if item["stage"] == "Officer Review": item["state"] = "COMPLETED" if action == "APPROVE" else "EXCEPTION"
        if item["stage"] == "Completed" and action == "APPROVE": item["state"], item["at"] = "COMPLETED", _now()
    return app
