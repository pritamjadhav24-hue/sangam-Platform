from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.core.audit_bus import audit_bus

APPLICATIONS: dict[str, dict] = {}
DEPENDENCIES: dict[str, dict] = {}
ENTITY_REVIEWS: dict[str, dict] = {}
CONFLICT_REVIEWS: dict[str, dict] = {}
_counter = itertools.count(142)
_review_counter = itertools.count(1)
_conflict_counter = itertools.count(1)
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
        event_bus.publish("APPLICATION_STATUS_CHANGED", {"appId": app["appId"], "citizenId": app["citizenId"], "status": status, "at": timestamp})
    return app


def find_active_application(citizen_id: str) -> dict | None:
    terminal = {"COMPLETED", "REJECTED", "CANCELLED"}
    return next((app for app in reversed(list(APPLICATIONS.values()))
                 if app["citizenId"] == citizen_id and app["status"] not in terminal), None)


def create_entity_reviews(app: dict) -> list[dict]:
    reviews = []
    for requirement in app["requirements"]:
        resolution = requirement.get("resolution", {})
        if resolution.get("confidenceLevel") != "MEDIUM":
            continue
        review_id = f"ER-{app['appId']}-{next(_review_counter):03d}"
        review = {
            "reviewId": review_id,
            "appId": app["appId"],
            "journeyId": app["appId"],
            "requirementCode": requirement["code"],
            "source": requirement["source"],
            "sourceRecordId": requirement.get("recordId"),
            "confidenceScore": resolution["score"],
            "confidenceLevel": resolution["confidenceLevel"],
            "matchedFields": resolution.get("matchedFields", []),
            "status": "WAITING_FOR_OFFICER",
            "decision": None,
            "createdAt": _now(),
            "updatedAt": _now(),
            "officerId": None,
        }
        ENTITY_REVIEWS[review_id] = review
        reviews.append(review)
        event_bus.publish("ENTITY_MATCH_REVIEW_REQUIRED", {"appId": app["appId"], "reviewId": review_id, "requirementCode": requirement["code"], "source": requirement["source"], "confidenceLevel": "MEDIUM"})
    return reviews


def entity_review_action(review_id: str, decision: str, officer_id: str, remarks: str):
    review = ENTITY_REVIEWS.get(review_id)
    if not review:
        return None, None
    if decision not in {"MATCH", "REJECT"} or not remarks.strip():
        raise ValueError("Entity review requires MATCH or REJECT and mandatory remarks.")
    app = APPLICATIONS.get(review["appId"])
    if not app:
        return None, None
    requirement = next((item for item in app["requirements"] if item["code"] == review["requirementCode"]), None)
    if not requirement:
        return None, None
    review.update({"status": "APPROVED" if decision == "MATCH" else "REJECTED", "decision": decision, "officerId": officer_id, "remarks": remarks, "updatedAt": _now()})
    requirement.setdefault("resolution", {}).update({"status": "MATCH" if decision == "MATCH" else "MISMATCH", "decision": "HUMAN_ACCEPTED" if decision == "MATCH" else "HUMAN_REJECTED", "reviewId": review_id})
    requirement["status"] = "FOUND" if decision == "MATCH" else "UNRESOLVED"
    if decision == "REJECT":
        transition_application(app, "VERIFICATION_FAILED")
    elif not any(item["status"] == "WAITING_FOR_OFFICER" for item in app.get("entityReviews", [])) and not any(item["status"] in {"REVIEW_REQUIRED", "UNRESOLVED"} for item in app["requirements"]):
        transition_application(app, "IN_PROGRESS")
    event_bus.publish("ENTITY_MATCH_DECIDED", {"appId": app["appId"], "reviewId": review_id, "requirementCode": requirement["code"], "decision": decision, "officerId": officer_id})
    return app, review


def create_conflict_reviews(app: dict) -> list[dict]:
    reviews = []
    for conflict in app.get("conflicts", []):
        review_id = f"CR-{app['appId']}-{next(_conflict_counter):03d}"
        review = {
            "reviewId": review_id, "conflictId": review_id, "appId": app["appId"], "journeyId": app["appId"],
            "requirementCode": conflict["requirementCode"], "canonicalField": conflict["canonicalField"],
            "sources": conflict["sources"], "status": "WAITING_FOR_OFFICER", "decision": None,
            "createdAt": conflict.get("detectedAt", _now()), "updatedAt": _now(), "officerId": None,
        }
        CONFLICT_REVIEWS[review_id] = review
        reviews.append(review)
        requirement = next((item for item in app["requirements"] if item["code"] == conflict["requirementCode"]), None)
        if requirement:
            requirement["status"] = "CONFLICT_DETECTED"
        event_bus.publish("CONFLICT_DETECTED", {"appId": app["appId"], "conflictId": review_id, "canonicalField": conflict["canonicalField"], "sources": [item["sourceSystem"] for item in conflict["sources"]]})
        audit_bus.append("SYSTEM", "CONFLICT", "Conflicting trusted source values detected", "Cross-system sources", "DETECT", app.get("consentId"), payload={"appId": app["appId"], "conflictId": review_id, "canonicalField": conflict["canonicalField"], "sources": [item["sourceSystem"] for item in conflict["sources"]]}, correlation_id=app["appId"])
    return reviews


def conflict_review_action(review_id: str, decision: str, officer_id: str, remarks: str, selected_source: str | None = None):
    review = CONFLICT_REVIEWS.get(review_id)
    if not review:
        return None, None
    if decision not in {"SELECT", "REJECT"} or not remarks.strip():
        raise ValueError("Conflict review requires SELECT or REJECT and mandatory remarks.")
    if decision == "SELECT" and not selected_source:
        raise ValueError("Select one trusted source before resolving the conflict.")
    selected = next((item for item in review["sources"] if item["sourceSystem"] == selected_source), None) if selected_source else None
    if decision == "SELECT" and not selected:
        raise ValueError("Selected source is not part of this conflict.")
    app = APPLICATIONS.get(review["appId"])
    if not app:
        return None, None
    requirement = next((item for item in app["requirements"] if item["code"] == review["requirementCode"]), None)
    if not requirement:
        return None, None
    review.update({"status": "RESOLVED" if decision == "SELECT" else "REJECTED", "decision": decision, "selectedSource": selected_source, "selectedValue": selected.get("value") if selected else None, "officerId": officer_id, "remarks": remarks, "updatedAt": _now()})
    conflict = next((item for item in app.get("conflicts", []) if item.get("canonicalField") == review["canonicalField"]), None)
    if conflict:
        conflict.update({"status": review["status"], "resolvedAt": review["updatedAt"], "selectedSource": selected_source, "selectedValue": selected.get("value") if selected else None})
    if decision == "SELECT":
        requirement["status"] = "FOUND"
        requirement.setdefault("canonical", {})[review["canonicalField"]] = selected["value"]
        requirement["provenance"] = {"sourceSystem": selected["sourceSystem"], "sourceRecordId": selected.get("sourceRecordId"), "sourceField": selected.get("sourceField")}
    else:
        requirement["status"] = "UNRESOLVED"
        transition_application(app, "VERIFICATION_FAILED")
    if decision == "SELECT" and not any(item["status"] == "WAITING_FOR_OFFICER" for item in app.get("conflictReviews", []) + app.get("entityReviews", [])) and not any(item["status"] in {"REVIEW_REQUIRED", "UNRESOLVED", "CONFLICT_DETECTED"} for item in app["requirements"]):
        transition_application(app, "IN_PROGRESS")
    event_bus.publish("CONFLICT_RESOLVED", {"appId": app["appId"], "conflictId": review_id, "canonicalField": review["canonicalField"], "decision": decision, "selectedSource": selected_source, "officerId": officer_id})
    return app, review


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
        "conflicts": discovery.get("conflicts", []), "conflictReviews": [],
    }
    APPLICATIONS[app_id] = app
    app["entityReviews"] = create_entity_reviews(app)
    app["conflictReviews"] = create_conflict_reviews(app)
    transition_application(app, "IN_PROGRESS")
    if app["conflictReviews"]:
        transition_application(app, "CONFLICT_DETECTED")
    elif app["entityReviews"]:
        transition_application(app, "WAITING_FOR_OFFICER")
    elif any(item.get("resolution", {}).get("confidenceLevel") == "LOW" for item in app["requirements"]):
        transition_application(app, "VERIFICATION_FAILED")
    elif requirement_map.get("DOMICILE_PROOF", {}).get("status") != "FOUND":
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
        if any(review["status"] == "WAITING_FOR_OFFICER" for review in app.get("entityReviews", []) + app.get("conflictReviews", [])):
            raise ValueError("All entity and conflict reviews must be decided before application approval.")
        if any(requirement["status"] in {"REVIEW_REQUIRED", "UNRESOLVED", "CONFLICT_DETECTED"} for requirement in app["requirements"]):
            raise ValueError("Application contains unresolved verification conflicts.")
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
