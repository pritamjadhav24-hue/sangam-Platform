from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.core.audit_bus import audit_bus
from app.engine.adapters import integration_health, is_integration_available
from app.engine.registry import select_dependency_provider
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
    provider_selection = select_dependency_provider("DOMICILE_PROOF", integration_health())
    if not provider_selection:
        raise ValueError("No registered provider can satisfy DOMICILE_PROOF")
    dependency = {
        "dependencyId": dependency_id,
        "appId": app["appId"],
        "journeyId": app["appId"],
        "requiredService": provider_selection["requiredService"],
        "requiredData": "DOMICILE_PROOF",
        "provider": provider_selection["provider"],
        "providerService": provider_selection["serviceId"],
        "serviceName": provider_selection["serviceName"],
        "adapter": provider_selection["adapter"],
        "providerSelection": {"requirementCode": provider_selection["requirementCode"], "requiredService": provider_selection["requiredService"], "provider": provider_selection["provider"], "adapter": provider_selection["adapter"], "serviceId": provider_selection["serviceId"], "reason": provider_selection["reason"], "healthStatus": provider_selection["healthStatus"], "selectedAt": timestamp},
        "status": "WAITING_FOR_DEPENDENCY",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "resultReference": None,
        "attempts": 0,
        "maxAttempts": 3,
        "providerStatus": provider_selection["healthStatus"],
        "lastError": None,
        "failureHistory": [],
    }
    DEPENDENCIES[dependency_id] = dependency
    app["dependencyIds"].append(dependency_id)
    app["dependencies"].append(dependency)
    if app.get("status") != "CONFLICT_DETECTED":
        transition_application(app, "WAITING_FOR_DEPENDENCY")
    event_bus.publish("MISSING_PREREQUISITE_DETECTED", {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency_id, "consentId": app.get("consentId"), "requiredData": "DOMICILE_PROOF"})
    event_bus.publish("DEPENDENCY_CREATED", {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency_id, "consentId": app.get("consentId"), "provider": dependency["provider"]})
    event_bus.publish("PROVIDER_SELECTED", {"appId": app["appId"], "dependencyId": dependency_id, "requiredService": dependency["requiredService"], "provider": dependency["provider"], "adapter": dependency["adapter"], "serviceId": dependency["providerService"], "healthStatus": provider_selection["healthStatus"]})
    audit_bus.append("SYSTEM", "PROVIDER_SELECTION", "Registered provider selected for missing canonical requirement", dependency["provider"], "SELECT", app.get("consentId"), payload={"appId": app["appId"], "dependencyId": dependency_id, "requiredService": dependency["requiredService"], "provider": dependency["provider"], "adapter": dependency["adapter"], "serviceId": dependency["providerService"], "healthStatus": provider_selection["healthStatus"]}, correlation_id=app["appId"])
    return dependency


def initiate_domicile(citizen_id: str, app: dict) -> dict:
    dependency = ensure_domicile_dependency(app)
    if dependency["status"] == "COMPLETED":
        return {"success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "service": "REV-MAHA-101", "message": "Domicile is already linked to the scholarship application.", "recordId": dependency["resultReference"], "attempts": dependency["attempts"]}
    dependency["attempts"] += 1
    dependency["updatedAt"] = _now()
    event_bus.publish("REVENUE_SERVICE_REQUESTED", {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "service": "REV-MAHA-101"})
    record = issue_domicile(citizen_id)
    if not record:
        dependency["status"] = "WAITING_FOR_DEPENDENCY"
        dependency["providerStatus"] = "UNAVAILABLE" if not is_integration_available("Revenue Department") else "DEGRADED"
        dependency["lastError"] = "Revenue Department domicile service unavailable."
        dependency["failureHistory"].append({"attempt": dependency["attempts"], "at": dependency["updatedAt"], "error": dependency["lastError"]})
        failure_payload = {"appId": app["appId"], "dependencyId": dependency["dependencyId"], "provider": dependency["provider"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "status": dependency["status"], "error": dependency["lastError"]}
        event_bus.publish("DEPENDENCY_SERVICE_FAILED", failure_payload)
        audit_bus.append("SYSTEM", "DEPENDENCY", "Revenue domicile service failure", dependency["provider"], "FAIL", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "error": dependency["lastError"]}, correlation_id=app["appId"])
        if dependency["attempts"] < dependency["maxAttempts"]:
            event_bus.publish("DEPENDENCY_RETRY_SCHEDULED", failure_payload)
            audit_bus.append("SYSTEM", "DEPENDENCY", "Bounded retry scheduled", dependency["provider"], "RETRY", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"]}, correlation_id=app["appId"])
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "attempts": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "providerStatus": dependency["providerStatus"], "message": "Revenue Department is unavailable; the same dependency remains waiting for retry."}

    dependency["status"] = "COMPLETED"
    dependency["updatedAt"] = _now()
    dependency["resultReference"] = record["recordId"]
    dependency["providerStatus"] = "AVAILABLE"
    dependency["lastError"] = None
    domicile = next((item for item in app["requirements"] if item["code"] == "DOMICILE_PROOF"), None)
    if domicile:
        domicile.update({"status": "FOUND", "recordId": record["recordId"], "canonical": map_record("DOMICILE_PROOF", record), "verifiedOn": record["validUntil"], "adapter": "REST API"})
    if not any(item.get("status") == "WAITING_FOR_OFFICER" for item in app.get("conflictReviews", []) + app.get("entityReviews", [])):
        transition_application(app, "IN_PROGRESS")
    event_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "recordId": record["recordId"], "service": "REV-MAHA-101"}
    event_bus.publish("DOMICILE_ISSUED", event_payload)
    event_bus.publish("DEPENDENCY_RESOLVED", event_payload)
    if dependency["attempts"] > 1:
        event_bus.publish("DEPENDENCY_RECOVERED", {**event_payload, "attempts": dependency["attempts"]})
        audit_bus.append("SYSTEM", "DEPENDENCY", "Revenue domicile service recovered", dependency["provider"], "RECOVER", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempts": dependency["attempts"]}, correlation_id=app["appId"])
    audit_bus.append("SYSTEM", "DEPENDENCY", "Revenue domicile service completed", dependency["provider"], "COMPLETE", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "resultReference": record["recordId"], "attempts": dependency["attempts"]}, correlation_id=app["appId"])
    event_bus.publish("WORKFLOW_RESUMED", {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "status": app["status"]})
    return {
        "success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"],
        "dependencyStatus": dependency["status"], "applicationStatus": app["status"],
        "service": "REV-MAHA-101", "message": "Domicile issued and linked to the scholarship application.",
        "recordId": record["recordId"],
    }
