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

VALID_TRANSITIONS = {
    "DRAFT": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"WAITING_FOR_DEPENDENCY", "WAITING_FOR_USER", "WAITING_FOR_OFFICER", "VERIFICATION_FAILED", "CONFLICT_DETECTED", "SUBMITTED", "CANCELLED"},
    "WAITING_FOR_DEPENDENCY": {"IN_PROGRESS", "CANCELLED", "VERIFICATION_FAILED"},
    "WAITING_FOR_USER": {"IN_PROGRESS", "SUBMITTED", "CANCELLED"},
    "WAITING_FOR_OFFICER": {"IN_PROGRESS", "APPROVED", "REJECTED", "WAITING_FOR_USER", "CANCELLED"},
    "VERIFICATION_FAILED": {"IN_PROGRESS", "WAITING_FOR_DEPENDENCY", "CANCELLED"},
    "CONFLICT_DETECTED": {"WAITING_FOR_OFFICER", "IN_PROGRESS", "VERIFICATION_FAILED", "CANCELLED"},
    "APPROVED": {"COMPLETED"},
    "SUBMITTED": {"WAITING_FOR_OFFICER", "CANCELLED"},
    "REJECTED": set(),
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def transition_application(app: dict, status: str, actor: str = "SYSTEM", source: str = "workflow_engine") -> dict:
    if status not in CANONICAL_STATUSES:
        raise ValueError(f"Unsupported application status: {status}")
    previous = app["status"]
    if previous == status:
        return app
    if status not in VALID_TRANSITIONS.get(previous, set()):
        raise ValueError(f"Invalid application transition: {previous} -> {status}")
    timestamp = _now()
    history_entry = {"status": status, "at": timestamp, "actor": actor, "source": source}
    app["status"] = status
    app["updatedAt"] = timestamp
    app.setdefault("statusHistory", []).append(history_entry)
    try:
        from app.core.persistence import persist_transition
        persist_transition(app, history_entry)
    except Exception:
        app["status"] = previous
        app["updatedAt"] = app.get("statusHistory", [{}])[-2].get("at", timestamp) if len(app.get("statusHistory", [])) > 1 else app.get("createdAt", timestamp)
        if app.get("statusHistory"):
            app["statusHistory"].pop()
        raise
    event_bus.publish("APPLICATION_STATUS_CHANGED", {"appId": app["appId"], "citizenId": app["citizenId"], "status": status, "at": timestamp, "actor": actor, "source": source})
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
            "fieldComparisons": resolution.get("fieldComparisons", []),
            "weights": resolution.get("weights", {}),
            "sourceSystem": resolution.get("sourceSystem", requirement["source"]),
            "candidateRecordId": resolution.get("candidateRecordId", requirement.get("recordId")),
            "provenance": resolution.get("provenance", requirement.get("provenance", {})),
            "explanation": resolution.get("explanation"),
            "status": "WAITING_FOR_OFFICER",
            "decision": None,
            "createdAt": _now(),
            "updatedAt": _now(),
            "officerId": None,
        }
        ENTITY_REVIEWS[review_id] = review
        reviews.append(review)
        event_bus.publish("ENTITY_REVIEW_CREATED", {"appId": app["appId"], "correlationId": app["appId"], "reviewId": review_id, "requirementCode": requirement["code"], "source": requirement["source"], "confidenceLevel": "MEDIUM"})
        event_bus.publish("ENTITY_MATCH_REVIEW_REQUIRED", {"citizenId": app["citizenId"], "appId": app["appId"], "reviewId": review_id, "requirementCode": requirement["code"], "source": requirement["source"], "confidenceLevel": "MEDIUM"})
    return reviews


def entity_review_action(review_id: str, decision: str, officer_id: str, remarks: str):
    review = ENTITY_REVIEWS.get(review_id)
    if not review:
        return None, None
    if decision not in {"MATCH", "REJECT"} or not remarks.strip():
        raise ValueError("Entity review requires MATCH or REJECT and mandatory remarks.")
    if review["status"] != "WAITING_FOR_OFFICER":
        if review.get("decision") == decision:
            app = APPLICATIONS.get(review["appId"])
            if app and decision == "MATCH" and app.get("status") == "WAITING_FOR_OFFICER":
                transition_application(app, "IN_PROGRESS")
            return app, review
        raise ValueError("Entity review has already been decided.")
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
    event_bus.publish("ENTITY_REVIEW_RESOLVED", {"appId": app["appId"], "correlationId": app["appId"], "reviewId": review_id, "requirementCode": requirement["code"], "decision": decision, "officerId": officer_id})
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
        event_bus.publish("CONFLICT_DETECTED", {"citizenId": app["citizenId"], "appId": app["appId"], "conflictId": review_id, "canonicalField": conflict["canonicalField"], "sources": [item["sourceSystem"] for item in conflict["sources"]]})
        audit_bus.append("SYSTEM", "CONFLICT", "Conflicting trusted source values detected", "Cross-system sources", "DETECT", app.get("consentId"), payload={"appId": app["appId"], "conflictId": review_id, "canonicalField": conflict["canonicalField"], "sources": [item["sourceSystem"] for item in conflict["sources"]]}, correlation_id=app["appId"])
    return reviews


def conflict_review_action(review_id: str, decision: str, officer_id: str, remarks: str, selected_source: str | None = None):
    review = CONFLICT_REVIEWS.get(review_id)
    if not review:
        return None, None
    if review["status"] != "WAITING_FOR_OFFICER":
        if review.get("decision") == decision and review.get("selectedSource") == selected_source:
            app = APPLICATIONS.get(review["appId"])
            if app and decision == "SELECT" and app.get("status") == "CONFLICT_DETECTED":
                transition_application(app, "IN_PROGRESS")
            return app, review
        raise ValueError("Conflict review has already been decided.")
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
    event_bus.publish("CONFLICT_RESOLVED", {"citizenId": app["citizenId"], "appId": app["appId"], "conflictId": review_id, "canonicalField": review["canonicalField"], "decision": decision, "selectedSource": selected_source, "officerId": officer_id})
    return app, review


def create_application(citizen_id: str, discovery: dict, eligibility: dict, service_id: str | None = None) -> dict:
    service_id = service_id or discovery.get("serviceId") or discovery.get("schemeId")
    app_id = f"SCH-MH-2026-{next(_counter):05d}" if service_id == "SCH-MH-2026" else f"APP-{service_id or 'SERVICE'}-{next(_counter):05d}"
    created_at = _now()
    requirement_map = {r["code"]: r for r in discovery["requirements"]}
    timeline = []
    configured_stages = discovery.get("workflowStages") or (STAGES if service_id == "SCH-MH-2026" else ["Submitted", "Requirements", "Verification", "Officer Review", "Completed"])
    for stage in configured_stages:
        lookup = {"Identity": "IDENTITY", "Income": "INCOME_PROOF", "Academic": "ACADEMIC_RECORD", "Domicile": "DOMICILE_PROOF"}.get(stage)
        if lookup is None:
            lookup = next((item["code"] for item in discovery["requirements"] if item.get("label") == stage), None)
        state = "COMPLETED" if lookup and requirement_map.get(lookup, {}).get("status") == "FOUND" else "PENDING"
        timeline.append({"stage": stage, "state": state, "at": created_at if state == "COMPLETED" else None})

    app = {
        "appId": app_id, "citizenId": citizen_id, "serviceId": service_id, "schemeId": service_id,
        "serviceName": discovery.get("service", {}).get("name") if isinstance(discovery.get("service"), dict) else discovery.get("serviceName"),
        "department": discovery.get("service", {}).get("department") if isinstance(discovery.get("service"), dict) else discovery.get("department"),
        "status": "DRAFT", "createdAt": created_at,
        "updatedAt": created_at, "requirements": discovery["requirements"], "eligibility": eligibility,
        "timeline": timeline, "statusHistory": [{"status": "DRAFT", "at": created_at}],
        "dependencyIds": [], "dependencies": [], "consentId": None, "officerRemarks": None,
        "conflicts": discovery.get("conflicts", []), "conflictReviews": [],
    }
    APPLICATIONS[app_id] = app
    event_bus.publish("APPLICATION_CREATED", {"citizenId": citizen_id, "appId": app_id, "correlationId": app_id, "source": "workflow_engine"})
    app["entityReviews"] = create_entity_reviews(app)
    app["conflictReviews"] = create_conflict_reviews(app)
    transition_application(app, "IN_PROGRESS")
    if app["conflictReviews"]:
        transition_application(app, "CONFLICT_DETECTED")
    elif app["entityReviews"]:
        transition_application(app, "WAITING_FOR_OFFICER")
    elif any(item.get("resolution", {}).get("confidenceLevel") == "LOW" for item in app["requirements"]):
        transition_application(app, "VERIFICATION_FAILED")
    elif any(item.get("status") != "FOUND" for item in app["requirements"]):
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    elif not eligibility["eligible"]:
        transition_application(app, "VERIFICATION_FAILED")
    return app


def officer_action(app_id: str, action: str, remarks: str):
    app = APPLICATIONS.get(app_id)
    if not app: return None
    if action not in {"APPROVE", "REJECT", "REQUEST_INFO"} or not remarks.strip(): raise ValueError("A decision and mandatory remarks are required.")
    if app["status"] == "COMPLETED" and action == "APPROVE":
        return app
    if app["status"] == "REJECTED" and action == "REJECT":
        return app
    if app["status"] in {"COMPLETED", "REJECTED", "CANCELLED"}:
        raise ValueError(f"Application is already {app['status']} and cannot accept {action}.")
    app["officerRemarks"] = remarks
    if action == "APPROVE":
        if any(review["status"] == "WAITING_FOR_OFFICER" for review in app.get("entityReviews", []) + app.get("conflictReviews", [])):
            raise ValueError("All entity and conflict reviews must be decided before application approval.")
        if any(requirement["status"] in {"REVIEW_REQUIRED", "UNRESOLVED", "CONFLICT_DETECTED"} for requirement in app["requirements"]):
            raise ValueError("Application contains unresolved verification conflicts.")
        transition_application(app, "APPROVED")
        transition_application(app, "COMPLETED")
        event_bus.publish("APPLICATION_COMPLETED", {"citizenId": app["citizenId"], "appId": app["appId"], "status": app["status"]})
    elif action == "REJECT":
        transition_application(app, "REJECTED")
        event_bus.publish("APPLICATION_REJECTED", {"citizenId": app["citizenId"], "appId": app["appId"], "status": app["status"]})
    else:
        transition_application(app, "WAITING_FOR_USER")
    for item in app["timeline"]:
        if item["stage"] == "Officer Review": item["state"] = "COMPLETED" if action == "APPROVE" else "EXCEPTION"
        if item["stage"] == "Completed" and action == "APPROVE": item["state"], item["at"] = "COMPLETED", _now()
    return app
