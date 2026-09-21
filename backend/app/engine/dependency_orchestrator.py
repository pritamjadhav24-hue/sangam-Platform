from __future__ import annotations

import itertools
import os
from datetime import datetime, timezone

from app.core.event_bus import event_bus
from app.core.audit_bus import audit_bus
from app.engine.adapters import integration_health, request_registered_service, service_available
from app.engine.registry import select_dependency_provider
from app.engine.semantic_mapper import map_record
from app.engine.workflow_engine import DEPENDENCIES, transition_application
from app.engine.consent_manager import CONSUMER, ConsentAuthorizationError, execute_with_persisted_authorization

_dependency_counter = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dependency(app: dict, requirement_code: str) -> dict:
    existing = next((DEPENDENCIES[dependency_id] for dependency_id in app.get("dependencyIds", [])
                     if dependency_id in DEPENDENCIES and DEPENDENCIES[dependency_id]["requiredData"] == requirement_code), None)
    if existing:
        return existing

    # Prevent a legacy dependency/application mutation from starting for an
    # application already owned by PostgreSQL. The persistence fence remains
    # the definitive check if authority changes after this advisory preflight.
    from app.core.persistence import assert_legacy_application_writable
    assert_legacy_application_writable(app["appId"])

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
        "providerId": provider_selection.get("providerId", provider_selection["provider"]),
        "providerService": provider_selection["serviceId"],
        "serviceName": provider_selection["serviceName"],
        "adapter": provider_selection["adapter"],
        "providerSelection": {"requirementCode": provider_selection["requirementCode"], "requiredService": provider_selection["requiredService"], "provider": provider_selection["provider"], "adapter": provider_selection["adapter"], "serviceId": provider_selection["serviceId"], "reason": provider_selection["reason"], "healthStatus": provider_selection["healthStatus"], "selectedAt": timestamp},
        "status": "WAITING_FOR_DEPENDENCY",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "resultReference": None,
        "attempts": 0,
        "maxAttempts": provider_selection.get("maxAttempts", 3),
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


def ensure_missing_dependencies(app: dict) -> list[dict]:
    """Create dependencies for configured requirements that are not resolved."""
    dependencies = []
    for requirement in app.get("requirements", []):
        if requirement.get("status") not in {"MISSING", "UNRESOLVED"}:
            continue
        try:
            dependencies.append(ensure_dependency(app, requirement["code"]))
        except ValueError:
            # A requirement without a registered capability remains a normal
            # unresolved requirement; it must not be silently completed.
            continue
    return dependencies


def initiate_dependency(citizen_id: str, app: dict, requirement_code: str, async_override: bool = False, authorized_adapter_result=None) -> dict:
    dependency = ensure_dependency(app, requirement_code)
    operation_consent_id = app.get("consentId")
    service_id = dependency.get("providerService") or dependency.get("serviceId")
    if dependency["status"] == "COMPLETED":
        return {"success": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "service": service_id, "message": "The required service result is already linked to the application.", "recordId": dependency["resultReference"], "attempts": dependency["attempts"]}
    if dependency["attempts"] >= dependency["maxAttempts"]:
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "attempts": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "providerStatus": dependency["providerStatus"], "message": "The dependency reached its retry limit and remains waiting for administrative recovery."}
    if os.getenv("ASYNC_PROVIDER_JOBS", "false").lower() in {"1", "true", "yes"} and not async_override:
        from app.core.job_queue import JobQueue
        from app.core.redis_service import RedisService
        if dependency.get("jobStatus") in {"QUEUED", "RUNNING"}:
            return {"success": False, "queued": True, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "message": "The provider request is already queued."}
        job = JobQueue(RedisService(enabled=True)).enqueue(
            "provider.dependency.retrieve", app["appId"], app["appId"], dependency["dependencyId"],
            {"serviceId": service_id, "requirementCode": requirement_code,
             "providerId": dependency.get("providerId"), "idempotencyKey": dependency["dependencyId"],
             "requestedAttributes": app.get("consentAttributes", []), "consentId": operation_consent_id,
             "maxAttempts": dependency["maxAttempts"]},
        )
        dependency.update({"jobId": job["jobId"], "jobStatus": "QUEUED", "updatedAt": _now()})
        event_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "correlationId": app["appId"], "jobId": job["jobId"], "service": service_id}
        event_bus.publish("PROVIDER_JOB_ENQUEUED", event_payload)
        audit_bus.append("SYSTEM", "DEPENDENCY", "Provider operation queued", dependency.get("provider", "CONFIGURED_PROVIDER"), "QUEUE", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "jobId": job["jobId"]}, correlation_id=app["appId"])
        return {"success": False, "queued": True, "jobId": job["jobId"], "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "message": "The provider request was queued for processing."}
    dependency["attempts"] += 1
    dependency["updatedAt"] = _now()
    event_bus.publish("REVENUE_SERVICE_REQUESTED", {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "consentId": app.get("consentId"), "service": service_id, "requiredData": requirement_code})
    adapter_result = authorized_adapter_result
    if adapter_result is None and service_id:
        adapter_result = execute_with_persisted_authorization(
            citizen_id, CONSUMER, None, requested_attributes=app.get("consentAttributes", []), service_id=app.get("serviceId"),
            application_id=app.get("appId"), consent_id=operation_consent_id,
            operation=lambda: request_registered_service(service_id, citizen_id, requirement_code=requirement_code, correlation_id=app["appId"], idempotency_key=dependency["dependencyId"]),
        )
    record = adapter_result.record if adapter_result else None
    dependency["lastRequest"] = {"correlationId": app["appId"], "idempotencyKey": dependency["dependencyId"], "operation": adapter_result.operation if adapter_result else "retrieve", "attempts": adapter_result.attempts if adapter_result else 0, "responseMs": adapter_result.response_ms if adapter_result else None}
    if not record:
        dependency["status"] = "WAITING_FOR_DEPENDENCY"
        dependency["providerStatus"] = "UNAVAILABLE" if not service_available(dependency["provider"]) else "DEGRADED"
        dependency["errorCategory"] = getattr(adapter_result, "error_category", None) or "UPSTREAM_UNAVAILABLE"
        dependency["lastError"] = f"{dependency['provider']} service unavailable."
        dependency["failureHistory"].append({"attempt": dependency["attempts"], "at": dependency["updatedAt"], "error": dependency["lastError"]})
        failure_payload = {"citizenId": citizen_id, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "provider": dependency["provider"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "status": dependency["status"], "error": dependency["lastError"]}
        event_bus.publish("DEPENDENCY_SERVICE_FAILED", failure_payload)
        event_bus.publish("DEPENDENCY_STATUS_CHANGED", {**failure_payload, "consentId": app.get("consentId")})
        audit_bus.append("SYSTEM", "DEPENDENCY", "Registered provider service failure", dependency["provider"], "FAIL", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "error": dependency["lastError"]}, correlation_id=app["appId"])
        if dependency["attempts"] < dependency["maxAttempts"]:
            event_bus.publish("DEPENDENCY_RETRY_SCHEDULED", failure_payload)
            audit_bus.append("SYSTEM", "DEPENDENCY", "Bounded retry scheduled", dependency["provider"], "RETRY", app.get("consentId"), payload={"dependencyId": dependency["dependencyId"], "attempt": dependency["attempts"], "maxAttempts": dependency["maxAttempts"]}, correlation_id=app["appId"])
        return {"success": False, "appId": app["appId"], "dependencyId": dependency["dependencyId"], "dependencyStatus": dependency["status"], "applicationStatus": app["status"], "attempts": dependency["attempts"], "maxAttempts": dependency["maxAttempts"], "providerStatus": dependency["providerStatus"], "message": f"{dependency['provider']} is unavailable; the same dependency remains waiting for retry."}

    dependency["status"] = "COMPLETED"
    dependency["updatedAt"] = _now()
    result_reference = record.get("recordId") or record.get("studentId") or record.get("id")
    if not result_reference:
        raise ValueError(f"Provider {dependency['provider']} returned no stable result identifier")
    dependency["resultReference"] = result_reference
    dependency["providerStatus"] = "AVAILABLE"
    dependency["errorCategory"] = None
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


def execute_provider_job(job: dict) -> dict:
    """Generic worker entry point: job -> dependency -> configured adapter."""
    from app.engine.workflow_engine import APPLICATIONS
    payload = job.get("payload", {})
    app = APPLICATIONS.get(job.get("applicationId"))
    dependency = DEPENDENCIES.get(job.get("dependencyId"))
    if not app or not dependency:
        raise RuntimeError("Provider job references missing application or dependency")
    if dependency.get("status") == "COMPLETED":
        return {"status": "ALREADY_COMPLETED", "dependencyId": dependency["dependencyId"]}
    requirement_code = payload.get("requirementCode", dependency.get("requiredData"))
    try:
        adapter_result = execute_with_persisted_authorization(
            app["citizenId"], CONSUMER, None, requested_attributes=payload.get("requestedAttributes", app.get("consentAttributes", [])), service_id=app.get("serviceId"),
            application_id=app.get("appId"), consent_id=payload.get("consentId") or app.get("consentId"),
            operation=lambda: request_registered_service(dependency.get("providerService"), app["citizenId"], requirement_code=requirement_code, correlation_id=app["appId"], idempotency_key=dependency["dependencyId"]),
        )
    except ConsentAuthorizationError as error:
        dependency.update({"jobStatus": "CANCELLED", "status": "WAITING_FOR_DEPENDENCY", "errorCategory": "AUTHORIZATION_ERROR", "lastError": "Provider operation was cancelled because consent is no longer valid.", "updatedAt": _now()})
        authorization_error = RuntimeError("Provider operation cancelled: consent is no longer valid.")
        authorization_error.category = "AUTHORIZATION_ERROR"
        authorization_error.retryable = False
        raise authorization_error from error
    result = initiate_dependency(payload.get("citizenId", app["citizenId"]), app, requirement_code, async_override=True, authorized_adapter_result=adapter_result)
    if result.get("success"):
        dependency.update({"jobId": job["jobId"], "jobStatus": "COMPLETED"})
        return result
    dependency["jobStatus"] = "WAITING"
    category = dependency.get("errorCategory") or "UPSTREAM_UNAVAILABLE"
    error = RuntimeError(result.get("message", "Provider operation failed"))
    error.category = category
    error.retryable = category in {"TRANSIENT", "TIMEOUT", "UPSTREAM_UNAVAILABLE", "UNAVAILABLE", "NETWORK"}
    raise error


def mark_provider_job_dead_letter(job: dict, category: str, message: str) -> None:
    from app.core.job_queue import safe_error_message
    from app.engine.workflow_engine import APPLICATIONS
    app = APPLICATIONS.get(job.get("applicationId"))
    dependency = DEPENDENCIES.get(job.get("dependencyId"))
    if not app or not dependency:
        return
    safe_message = safe_error_message(message)
    dependency.update({"jobStatus": "DEAD_LETTER", "errorCategory": category, "lastError": safe_message, "updatedAt": _now()})
    payload = {"citizenId": app["citizenId"], "appId": app["appId"], "dependencyId": dependency["dependencyId"], "jobId": job["jobId"], "correlationId": job["correlationId"], "provider": dependency.get("provider"), "errorCategory": category, "error": safe_message}
    event_bus.publish("PROVIDER_JOB_DEAD_LETTER", payload)
    event_bus.publish("DEPENDENCY_SERVICE_FAILED", payload)
    audit_bus.append("SYSTEM", "DEPENDENCY", "Provider operation moved to dead letter", dependency.get("provider", "CONFIGURED_PROVIDER"), "DEAD_LETTER", app.get("consentId"), payload=payload, correlation_id=job["correlationId"])


def mark_provider_job_cancelled(job: dict, category: str, message: str) -> None:
    from app.core.job_queue import safe_error_message
    dependency = DEPENDENCIES.get(job.get("dependencyId"))
    app = __import__("app.engine.workflow_engine", fromlist=["APPLICATIONS"]).APPLICATIONS.get(job.get("applicationId"))
    if not app or not dependency:
        return
    safe_message = safe_error_message(message)
    dependency.update({"jobStatus": "CANCELLED", "errorCategory": category, "lastError": safe_message, "updatedAt": _now()})
    payload = {"appId": app["appId"], "dependencyId": dependency["dependencyId"], "jobId": job["jobId"], "correlationId": job["correlationId"], "errorCategory": category, "error": safe_message}
    event_bus.publish("PROVIDER_JOB_CANCELLED", payload)
    audit_bus.append("SYSTEM", "DEPENDENCY", "Provider operation cancelled", "Configured provider", "CANCEL", app.get("consentId"), payload=payload, correlation_id=job["correlationId"])
