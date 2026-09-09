from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.engine.semantic_mapper import map_record
from app.engine.workflow_engine import DEPENDENCIES, transition_application
from app.mocks.revenue_dept import issue_domicile

_dependency_counter = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_domicile_dependency(app: dict) -> dict:
    existing = next((DEPENDENCIES[dependency_id] for dependency_id in app.get("dependencyIds", [])
                     if dependency_id in DEPENDENCIES and DEPENDENCIES[dependency_id]["requiredData"] == "DOMICILE_PROOF"), None)
    if existing:
        return existing

    timestamp = _now()
    dependency_id = f"DEP-{app['appId']}-{next(_dependency_counter):03d}"
    dependency = {
        "dependencyId": dependency_id,
        "appId": app["appId"],
        "journeyId": app["appId"],
        "requiredService": "Domicile Certificate",
        "requiredData": "DOMICILE_PROOF",
        "provider": "Revenue Department",
        "providerService": "REV-MAHA-101",
        "status": "WAITING_FOR_DEPENDENCY",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "resultReference": None,
    }
    DEPENDENCIES[dependency_id] = dependency
    app["dependencyIds"].append(dependency_id)
    app["dependencies"].append(dependency)
    transition_application(app, "WAITING_FOR_DEPENDENCY")
    return dependency


def initiate_domicile(citizen_id: str, app: dict) -> dict:
    dependency = ensure_domicile_dependency(app)
    record = issue_domicile(citizen_id)
    if not record:
        dependency["status"] = "VERIFICATION_FAILED"
        dependency["updatedAt"] = _now()
        transition_application(app, "VERIFICATION_FAILED")
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "message": "Domicile service could not issue a record."}

    dependency["status"] = "COMPLETED"
    dependency["updatedAt"] = _now()
    dependency["resultReference"] = record["recordId"]
    domicile = next((item for item in app["requirements"] if item["code"] == "DOMICILE_PROOF"), None)
    if domicile:
        domicile.update({"status": "FOUND", "recordId": record["recordId"], "canonical": map_record("DOMICILE_PROOF", record), "verifiedOn": record["validUntil"], "adapter": "REST API"})
    transition_application(app, "IN_PROGRESS")
    event_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "recordId": record["recordId"], "service": "REV-MAHA-101"}
    event_bus.publish("DOMICILE_ISSUED", event_payload)
    event_bus.publish("DEPENDENCY_RESOLVED", event_payload)
    return {
        "success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"],
        "dependencyStatus": dependency["status"], "applicationStatus": app["status"],
        "service": "REV-MAHA-101", "message": "Domicile issued and linked to the scholarship application.",
        "recordId": record["recordId"],
    }
