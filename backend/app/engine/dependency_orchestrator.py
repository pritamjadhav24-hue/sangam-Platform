from __future__ import annotations

import itertools
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.core.audit_bus import audit_bus
from app.engine.adapters import fetch_registered_service, integration_health, service_available
from app.engine.registry import select_dependency_provider
from app.engine.semantic_mapper import map_record
from app.engine.workflow_engine import DEPENDENCIES, transition_application

_dependency_counter = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dependency(app: dict, requirement_code: str) -> dict:
    existing = next((DEPENDENCIES[dependency_id] for dependency_id in app.get("dependencyIds", [])
                     if dependency_id in DEPENDENCIES and DEPENDENCIES[dependency_id]["requiredData"] == requirement_code), None)
    if existing:
        return existing

    timestamp = _now()
    dependency_id = f"DEP-{app['appId']}-{next(_dependency_counter):03d}"
    provider_selection = select_dependency_provider(requirement_code, integration_health())
    if not provider_selection:
        raise ValueError(f"No registered provider can satisfy {requirement_code}")
    dependency = {
        "dependencyId": dependency_id,
        "appId": app["appId"],
        "journeyId": app["appId"],
        "requiredService": provider_selection["requiredService"],
        "requiredData": requirement_code,
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
    event_bus.publish("MISSING_PREREQUISITE_DETECTED", {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency_id, "consentId": app.get("consentId"), "requiredData": requirement_code})
    event_bus.publish("DEPENDENCY_CREATED", {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency_id, "consentId": app.get("consentId"), "provider": dependency["provider"]})
    event_bus.publish("DEPENDENCY_STATUS_CHANGED", {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency_id, "consentId": app.get("consentId"), "status": dependency["status"]})
    event_bus.publish("PROVIDER_SELECTED", {"appId": app["appId"], "dependencyId": dependency_id, "requiredService": dependency["requiredService"], "provider": dependency["provider"], "adapter": dependency["adapter"], "serviceId": dependency["providerService"], "healthStatus": provider_selection["healthStatus"]})
    audit_bus.append("SYSTEM", "PROVIDER_SELECTION", "Registered provider selected for missing canonical requirement", dependency["provider"], "SELECT", app.get("consentId"), payload={"appId": app["appId"], "dependencyId": dependency_id, "requiredService": dependency["requiredService"], "provider": dependency["provider"], "adapter": dependency["adapter"], "serviceId": dependency["providerService"], "healthStatus": provider_selection["healthStatus"]}, correlation_id=app["appId"])
    return dependency


def ensure_domicile_dependency(app: dict) -> dict:
    return ensure_dependency(app, "DOMICILE_PROOF")


def initiate_dependency(citizen_id: str, app: dict, requirement_code: str) -> dict:
    dependency = ensure_dependency(app, requirement_code)
    service_id = dependency.get("providerService") or dependency.get("serviceId")
    if dependency["status"] == "COMPLETED":
        return {"success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "service": service_id, "message": "The required service result is already linked to the application.", "recordId": dependency["resultReference"], "attempts": dependency["attempts"]}
    if dependency["attempts"] >= dependency["maxAttempts"]:
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "attempts": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "providerStatus": dependency["providerStatus"], "message": "The dependency reached its retry limit and remains waiting for administrative recovery."}
    dependency["attempts"] += 1
    dependency["updatedAt"] = _now()
    event_bus.publish("REVENUE_SERVICE_REQUESTED", {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "service": service_id, "requiredData": requirement_code})
    record = fetch_registered_service(service_id, citizen_id) if service_id else None
    if not record:
        dependency["status"] = "WAITING_FOR_DEPENDENCY"
        dependency["providerStatus"] = "UNAVAILABLE" if not service_available(dependency["provider"]) else "DEGRADED"
        dependency["lastError"] = f"{dependency['provider']} service unavailable."
        dependency["failureHistory"].append({"attempt": dependency["attempts"], "at": dependency["updatedAt"], "error": dependency["lastError"]})
        failure_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "provider": dependency["provider"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "status": dependency["status"], "error": dependency["lastError"]}
        event_bus.publish("DEPENDENCY_SERVICE_FAILED", failure_payload)
        event_bus.publish("DEPENDENCY_STATUS_CHANGED", {**failure_payload, "consentId": app.get("consentId")})
        audit_bus.append("SYSTEM", "DEPENDENCY", "Registered provider service failure", dependency["provider"], "FAIL", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "error": dependency["lastError"]}, correlation_id=app["appId"])
        if dependency["attempts"] < dependency["maxAttempts"]:
            event_bus.publish("DEPENDENCY_RETRY_SCHEDULED", failure_payload)
            audit_bus.append("SYSTEM", "DEPENDENCY", "Bounded retry scheduled", dependency["provider"], "RETRY", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"]}, correlation_id=app["appId"])
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "attempts": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "providerStatus": dependency["providerStatus"], "message": "Revenue Department is unavailable; the same dependency remains waiting for retry."}

    dependency["status"] = "COMPLETED"
    dependency["updatedAt"] = _now()
    result_reference = record.get("recordId") or record.get("studentId") or record.get("id")
    if not result_reference:
        raise ValueError(f"Provider {dependency['provider']} returned no stable result identifier")
    dependency["resultReference"] = result_reference
    dependency["providerStatus"] = "AVAILABLE"
    dependency["lastError"] = None
    domicile = next((item for item in app["requirements"] if item["code"] == requirement_code), None)
    if domicile:
        domicile.update({"status": "FOUND", "recordId": result_reference, "canonical": map_record(requirement_code, record), "verifiedOn": record.get("validUntil"), "adapter": dependency["adapter"]})
    if not any(item.get("status") == "WAITING_FOR_OFFICER" for item in app.get("conflictReviews", []) + app.get("entityReviews", [])):
        transition_application(app, "IN_PROGRESS")
    event_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "recordId": result_reference, "service": service_id, "requiredData": requirement_code}
    event_bus.publish("DOMICILE_ISSUED", event_payload)
    event_bus.publish("DEPENDENCY_RESOLVED", event_payload)
    event_bus.publish("DEPENDENCY_STATUS_CHANGED", {**event_payload, "status": dependency["status"]})
    if dependency["attempts"] > 1:
        event_bus.publish("DEPENDENCY_RECOVERED", {**event_payload, "attempts": dependency["attempts"]})
        event_bus.publish("RETRY_SUCCEEDED", {**event_payload, "attempts": dependency["attempts"]})
        audit_bus.append("SYSTEM", "DEPENDENCY", "Registered provider service recovered", dependency["provider"], "RECOVER", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempts": dependency["attempts"]}, correlation_id=app["appId"])
    audit_bus.append("SYSTEM", "DEPENDENCY", "Registered provider service completed", dependency["provider"], "COMPLETE", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "resultReference": result_reference, "attempts": dependency["attempts"]}, correlation_id=app["appId"])
    event_bus.publish("WORKFLOW_RESUMED", {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "status": app["status"]})
    return {
        "success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"],
        "dependencyStatus": dependency["status"], "applicationStatus": app["status"],
        "service": service_id, "message": "The provider result was linked to the application.",
        "recordId": result_reference,
    }


def initiate_domicile(citizen_id: str, app: dict) -> dict:
    return initiate_dependency(citizen_id, app, "DOMICILE_PROOF")
