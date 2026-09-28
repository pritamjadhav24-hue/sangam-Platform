"""Per-requirement Auto-Fill execution for Phase 6B/6C authoritative applications.

Phase 6B applications (``persistence.create_application``) are PostgreSQL-
authoritative from creation. The legacy dependency/retrieval path
(``dependency_orchestrator.ensure_dependency`` / ``initiate_dependency`` /
``artifact_retrieval.retrieve_artifact``) cannot be reused here:
``ensure_dependency`` unconditionally calls ``transition_application()``,
which ``assert_legacy_application_writable()`` correctly rejects for any
application whose ``authoritative_at`` is already set -- the identical
conflict Phase 6B's manual-upload endpoint already hit and resolved the same
way this module does.

This module is the authoritative-safe equivalent for real Auto-Fill
retrieval. It does not reimplement or bypass any other engine: provider
discovery (``registry.select_dependency_provider``), the adapter boundary
(``adapters.request_registered_service``), schema mapping (already applied
inside ``DepartmentSandboxAPIAdapter.normalize`` via
``schema_mapping.apply_schema_mapping``), validation
(``validation_engine.validate``), consent
(``consent_manager.create_consent`` / ``execute_with_persisted_
authorization``) and failure classification (``retry_policy``) are all
reused unchanged. Only the persistence step differs: results are written
through ``persistence.mutate_application`` -- the same authoritative gateway
Phase 6B's manual upload already uses -- never the legacy in-memory dict.

Every Auto-Fill attempt runs a fresh ``select_dependency_provider`` call, so
a retry naturally re-discovers the best currently-eligible provider with no
separate fallback mechanism needed here (unlike the legacy dependency object,
which pins one provider until ``retry_policy.attempt_provider_fallback``
explicitly re-points it).
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from app.core.audit_bus import audit_bus
from app.engine import retry_policy
from app.engine.adapters import AdapterResult, health_for_selection, integration_health, request_registered_service
from app.engine.artifact_retrieval import _source_category_for_provider, is_document_requirement
from app.engine.consent_manager import CONSUMER, execute_with_persisted_authorization
from app.engine.registry import dependency_registry, select_dependency_provider
from app.engine.validation_engine import validate

# Hard ceiling on providers tried within one cascade, purely as a defensive
# bound against a registry-configuration bug -- normal operation always
# terminates earlier, either on success or because find_fallback_candidate
# naturally runs out of eligible, not-yet-tried candidates.
MAX_CASCADE_ATTEMPTS = 10

AUTO_FILL_PURPOSE_PREFIX = "AUTO_FILL:"
SUCCESS_STATUSES = frozenset({"VALIDATED", "RETRIEVED"})
TERMINAL_STATUSES = frozenset({"VALIDATED", "RETRIEVED", "REJECTED"})
# workflow_engine.CANONICAL_STATUSES' "SUBMITTED" value -- once an
# application has been submitted (Phase 6E), requirement-level mutation
# (Auto-Fill, reject, manual upload) is no longer allowed. Referenced by its
# literal value rather than imported to avoid a circular import with
# app.engine.submission, which itself imports SUCCESS_STATUSES from here.
SUBMITTED_APPLICATION_STATUS = "SUBMITTED"


class ApplicationSubmittedError(RuntimeError):
    """Raised when a requirement-level mutation (Auto-Fill, reject, manual
    upload) is attempted against an application that has already been
    submitted. Callers map this to a 409 Conflict."""


def auto_fill_purpose(requirement_code: str) -> str:
    """Purpose string binding a consent receipt to this exact requirement,
    never reused across a different requirement's retrieval."""
    return f"{AUTO_FILL_PURPOSE_PREFIX}{requirement_code}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_id(app_id: str, requirement_code: str) -> str:
    return f"DOC-{app_id}-{requirement_code}"


def find_requirement(application: dict, requirement_code: str) -> Optional[dict]:
    return next((item for item in application.get("requirements", []) if item.get("code") == requirement_code), None)


def _discover_and_retrieve(requirement_code: str, citizen_id: str, application_id: str, correlation_id: Optional[str],
                            consent_id: Optional[str] = None) -> tuple[AdapterResult, list[dict]]:
    """Fresh, server-side-only provider discovery + adapter call for exactly
    this requirement, cascading through every eligible fallback provider
    within this ONE fulfillment operation on a retryable failure -- the
    citizen never has to click Auto-Fill again for a fallback to happen.
    The frontend has no way to influence which provider is selected -- this
    function takes no provider/department input at all.

    Reuses select_dependency_provider/find_fallback_candidate for discovery
    (no second selection algorithm) and retry_policy.is_retryable_category
    for classification (no second failure taxonomy). A provider already
    tried in this cascade is never selected again here; a later, separate
    fulfill_requirement() call (e.g. the citizen manually retrying) is free
    to reconsider it, since attempts/maxAttempts on the requirement -- not
    this per-call exclusion set -- is what governs retry across calls.

    Returns (final_result, attempt_log); attempt_log records every provider
    tried, in order, for the caller to persist as lineage.
    """
    tried_provider_ids: set[str] = set()
    attempt_log: list[dict] = []
    health = health_for_selection()  # records a just-detected outage/recovery (incident timing)
    selected = select_dependency_provider(requirement_code, health)
    result: Optional[AdapterResult] = None

    # Higher-priority providers that discovery passed over because their
    # current health excluded them (e.g. an open outage) are part of this
    # operation's real lineage: without them, a provider selected only
    # because the primary was down would be reported as if it were the
    # primary. Same registry + ordering select_dependency_provider uses.
    from app.engine.provider_policy import is_selectable, item_role, selection_key
    rank = selection_key

    ranked = sorted((item for item in dependency_registry(health) if item["requirementCode"] == requirement_code and is_selectable(item)), key=rank)
    roles = {item.get("providerId"): item_role(item) for item in ranked}
    for candidate in ranked:
        if selected and rank(candidate) >= rank(selected):
            break
        if candidate.get("healthStatus") in {"AVAILABLE", "HEALTHY"}:
            continue
        attempt_log.append({
            "providerId": candidate.get("providerId"), "provider": candidate.get("provider"), "isFallback": bool(attempt_log),
            "success": False, "skipped": True, "healthStatus": candidate.get("healthStatus"), "errorCategory": "UPSTREAM_UNAVAILABLE",
            "role": item_role(candidate), "at": _now(),
        })
        audit_bus.append(
            "SYSTEM", requirement_code, "Provider skipped: currently unavailable", candidate.get("provider"), "SKIPPED", consent_id,
            payload={"appId": application_id, "requirementCode": requirement_code, "providerId": candidate.get("providerId"),
                     "healthStatus": candidate.get("healthStatus")},
            correlation_id=application_id,
        )
    if selected is None and attempt_log:
        # Providers exist for this requirement but none is currently
        # healthy: a transient outage (retryable), not a configuration gap.
        return AdapterResult(None, correlation_id=correlation_id, error_category="UPSTREAM_UNAVAILABLE", success=False, retryable=True), attempt_log

    while selected and len(attempt_log) < MAX_CASCADE_ATTEMPTS:
        provider_id = selected.get("providerId") or selected.get("provider")
        provider_name = selected.get("provider")
        is_fallback = bool(attempt_log)
        audit_bus.append(
            "SYSTEM", requirement_code,
            "Fallback provider selected after primary provider failure" if is_fallback else "Primary provider selected for requirement",
            provider_name, "FALLBACK_SELECTED" if is_fallback else "SELECT", consent_id,
            payload={"appId": application_id, "requirementCode": requirement_code, "providerId": provider_id,
                     "attemptNumber": len(attempt_log) + 1, "isFallback": is_fallback},
            correlation_id=application_id,
        )
        started_at = _now()
        result = request_registered_service(
            selected["serviceId"], citizen_id, requirement_code=requirement_code,
            correlation_id=correlation_id, idempotency_key=f"{application_id}:{requirement_code}",
        )
        tried_provider_ids.add(provider_id)
        record_not_found = bool((result.metadata or {}).get("recordNotFound")) and not result.success
        attempt_log.append({
            "providerId": provider_id, "provider": provider_name, "isFallback": is_fallback,
            "success": bool(result.success), "errorCategory": result.error_category,
            "role": roles.get(provider_id) or item_role(selected), "at": started_at, "completedAt": _now(),
            **({"recordNotFound": True} if record_not_found else {}),
            **({"lookupResult": (result.metadata or {}).get("lookupResult")} if (result.metadata or {}).get("lookupResult") else {}),
        })
        if result.success:
            audit_bus.append(
                "SYSTEM", requirement_code, "Provider retrieval succeeded", provider_name, "RETRIEVED", consent_id,
                payload={"appId": application_id, "requirementCode": requirement_code, "providerId": provider_id, "isFallback": is_fallback},
                correlation_id=application_id,
            )
            return result, attempt_log

        category = result.error_category or "UPSTREAM_UNAVAILABLE"
        audit_bus.append(
            "SYSTEM", requirement_code, "Provider attempt failed", provider_name, "FAIL", consent_id,
            payload={"appId": application_id, "requirementCode": requirement_code, "providerId": provider_id, "errorCategory": category},
            correlation_id=application_id,
        )
        primary_unreachable = any(entry.get("skipped") or retry_policy.is_retryable_category(entry.get("errorCategory") or "")
                                  for entry in attempt_log[:-1])
        if not retry_policy.is_retryable_category(category):
            if category == "VALIDATION_ERROR" and (primary_unreachable or record_not_found):
                # "No record" from one department is not "no record" for the
                # citizen: the record may be kept by another department
                # registered for the same requirement, so ask the next one in
                # the registry's order. Only when every capable provider has
                # answered is it "no record"; if a higher-priority source
                # could not be asked at all, it is "not available right now".
                selected = retry_policy.find_fallback_candidate(requirement_code, exclude_provider_ids=tried_provider_ids)
                if selected is None:
                    # Every *reachable* authorized provider has answered. If an
                    # authorized provider could not be asked (unhealthy, so not
                    # a candidate), "no record" would be a false claim.
                    logged = {entry.get("providerId") for entry in attempt_log}
                    unasked = [item for item in ranked if item.get("providerId") not in logged
                               and item.get("healthStatus") not in {"AVAILABLE", "HEALTHY"}]
                    if primary_unreachable or unasked:
                        for item in unasked:
                            attempt_log.append({"providerId": item.get("providerId"), "provider": item.get("provider"), "isFallback": True,
                                                "success": False, "skipped": True, "healthStatus": item.get("healthStatus"),
                                                "errorCategory": "UPSTREAM_UNAVAILABLE", "role": item_role(item), "at": _now()})
                        return AdapterResult(None, correlation_id=correlation_id, error_category="UPSTREAM_UNAVAILABLE", success=False, retryable=True), attempt_log
                    return result, attempt_log
                continue
            # Non-retryable (validation/auth/config/etc.) -- the existing
            # policy says this terminates immediately, never falls back.
            return result, attempt_log
        selected = retry_policy.find_fallback_candidate(requirement_code, exclude_provider_ids=tried_provider_ids)

    if result is None:
        # No eligible provider existed even for the first attempt.
        return AdapterResult(None, correlation_id=correlation_id, error_category="CONFIGURATION_ERROR", success=False, retryable=False), attempt_log
    return result, attempt_log


PROVIDER_HISTORY_LIMIT = 25


def _apply_outcome(requirement: dict, adapter_result: Optional[AdapterResult], attempt_log: Optional[list[dict]] = None) -> bool:
    """Apply one outcome (see _apply_outcome_to_requirement) and, when it was
    applied, append a timestamped record of the operation -- every provider
    tried and the resulting requirement status -- to ``providerHistory``.
    ``fallbackAttempts`` only ever holds the latest operation; this history
    is what lets Admin incident impact tie past failures, fallbacks and
    recoveries to an incident's time window."""
    applied = _apply_outcome_to_requirement(requirement, adapter_result, attempt_log)
    if applied and attempt_log:
        history = list(requirement.get("providerHistory") or [])
        history.append({
            "at": _now(), "outcome": requirement.get("status"),
            "attempts": [{key: attempt.get(key) for key in ("providerId", "provider", "success", "skipped", "errorCategory", "recordNotFound", "role")} for attempt in attempt_log],
        })
        requirement["providerHistory"] = history[-PROVIDER_HISTORY_LIMIT:]
    return applied


def _apply_outcome_to_requirement(requirement: dict, adapter_result: Optional[AdapterResult], attempt_log: Optional[list[dict]] = None) -> bool:
    """Mutate the requirement dict in place from one adapter outcome. Returns
    whether the outcome was actually applied (``False`` for a stale no-op --
    see below), so the caller knows whether to also touch the document
    reference for this requirement.

    Reuses the existing schema-mapped canonical output, the existing
    validation engine, and the existing retry-classification taxonomy
    (``retry_policy``) -- duck-typed onto the requirement dict the same way
    it already reads a legacy dependency dict, since both simply carry
    attempts/maxAttempts/errorCategory/status fields.
    """
    if requirement.get("status") in SUCCESS_STATUSES:
        # A newer attempt (another concurrent Auto-Fill, or a citizen manual
        # upload) already satisfied this requirement while this outcome's
        # provider call was still in flight. This outcome is stale -- win or
        # lose, it must never overwrite an already-achieved result. This is
        # only reachable at all because the caller re-reads the requirement
        # fresh under the same row lock it writes with (see
        # mutate_requirement_under_lock); the route's own pre-check normally
        # short-circuits a request for an already-successful requirement
        # before any provider call even starts.
        return False
    requirement["attempts"] = requirement.get("attempts", 0) + 1
    requirement["maxAttempts"] = requirement.get("maxAttempts", 3)
    requirement.pop("autoFillRequestedAt", None)
    if attempt_log:
        # Ground truth for Admin visibility (app.api.admin_routes) of
        # exactly which providers this operation tried, in order -- more
        # precise than inferring "was this a fallback" from the provider
        # currently ranked first, which can drift after a later recovery.
        requirement["fallbackAttempts"] = attempt_log
        requirement["isFallback"] = attempt_log[-1]["isFallback"] and not attempt_log[-1].get("skipped")
        answered = next((entry for entry in reversed(attempt_log) if entry.get("success")), None)
        requirement["servedByRole"] = (answered or {}).get("role")
        # Whether any department's own lookup was ambiguous -- "more than one
        # person could match", which is not the same as "no record".
        if any(entry.get("lookupResult") == "AMBIGUOUS" for entry in attempt_log):
            requirement["lookupOutcome"] = "AMBIGUOUS"
        else:
            requirement.pop("lookupOutcome", None)
    record = adapter_result.record if adapter_result else None
    if record:
        match = (adapter_result.metadata or {}).get("identityMatch")
        if match is not None:
            requirement["identityMatch"] = {key: match.get(key) for key in (
                "status", "decision", "confidenceLevel", "score", "matchedFields", "fieldComparisons", "explanation",
                "matchCategory", "departmentMatchMethod")}
            if match.get("decision") != "AUTO_ACCEPT":
                # Never attach a record that may belong to someone else: the
                # requirement stays open and the citizen can upload it instead.
                requirement.update({"status": "ACTION_REQUIRED", "errorCategory": "IDENTITY_UNCONFIRMED",
                                    "lastError": "Unable to confirm the record", "providerId": adapter_result.provider_id,
                                    "resultReference": record.get("id")})
                requirement.pop("canonical", None)
                requirement.pop("provenance", None)
                return True
        else:
            requirement.pop("identityMatch", None)
        # Prefer the adapter's own schema_mappings-derived canonical view
        # when it provides one (DepartmentSandboxAPIAdapter.normalize); other
        # provider types don't set "canonical" at all, so fall back to the
        # existing deterministic per-requirement rules -- the exact same
        # fallback dependency_orchestrator.initiate_dependency already uses.
        from app.engine.semantic_mapper import map_record

        canonical = record["canonical"] if isinstance(record, dict) and "canonical" in record else map_record(requirement["code"], record)
        validation = validate(requirement["code"], canonical, record)
        requirement["canonical"] = canonical
        requirement["validation"] = validation
        requirement["errorCategory"] = None
        requirement["lastError"] = None
        requirement["resultReference"] = record.get("id")
        requirement["providerId"] = adapter_result.provider_id
        from app.engine.departments import provider_department
        requirement["sourceDepartment"] = provider_department(adapter_result.provider_id)
        requirement["verifiedAt"] = _now()
        requirement["provenance"] = _provenance(requirement, record, match)
        if validation["valid"]:
            requirement["status"] = "VALIDATED" if is_document_requirement(requirement["code"]) else "RETRIEVED"
            requirement["verifiedOn"] = record.get("validUntil")
        else:
            requirement["status"] = "REJECTED"
        return True
    category = getattr(adapter_result, "error_category", None) or "UPSTREAM_UNAVAILABLE"
    requirement["errorCategory"] = category
    requirement["lastError"] = "The requested information could not be retrieved at this time."
    classification = retry_policy.classify_dependency_failure(requirement)
    if not classification["retryable"]:
        requirement["status"] = "FAILED"
    elif classification["attemptsExhausted"]:
        requirement["status"] = "ACTION_REQUIRED"
    else:
        requirement["status"] = "WAITING"
    return True


def _provenance(requirement: dict, record: dict, match: Optional[dict]) -> dict:
    """Where a verified value came from, kept with the requirement: the
    department and provider, the department's own record id, when and how it
    was verified, and how sure SANGAM is that it is this citizen's."""
    department_match = record.get("departmentMatch") or {}
    raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
    identified = department_match.get("method") in {"DEPARTMENT_IDENTIFIER", "CROSS_REFERENCE"}
    return {
        "sourceDepartment": requirement.get("sourceDepartment"),
        "providerId": requirement.get("providerId"),
        "sourceRecordId": record.get("id"),
        "verifiedAt": requirement.get("verifiedAt"),
        # A department API answering from its own register: structured,
        # verified data. A file is only ever attached when the department
        # itself supplies one -- SANGAM never generates a document.
        "verificationMethod": "DEPARTMENT_API_RECORD",
        "recordKind": "DOCUMENT" if isinstance(raw.get("document"), dict) else "STRUCTURED_RECORD",
        # "Fallback" means an explicitly authorized fallback answered -- not
        # merely that a second provider was asked.
        "fallbackUsed": requirement.get("servedByRole") == "AUTHORIZED_FALLBACK" if requirement.get("servedByRole") else bool(requirement.get("isFallback")),
        "authorizationRole": requirement.get("servedByRole"),
        "departmentMatchMethod": department_match.get("method"),
        "matchCategory": (match or {}).get("matchCategory") or ("EXACT" if identified else None),
        "confidence": (match or {}).get("score"),
        "confidenceLevel": (match or {}).get("confidenceLevel"),
    }


# ---------------------------------------------------------------------------
# Interoperability trace: what SANGAM did between the requesting department's
# application and the department that answered. Sanitized by construction --
# department/provider names, requirement codes, outcomes and timestamps only;
# never identities, record contents, credentials or database details.
# ---------------------------------------------------------------------------

_OUTAGE = {"UPSTREAM_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT", "UPSTREAM_ERROR", "RATE_LIMITED"}


def _consumer_department(application: dict) -> Optional[str]:
    """The department whose service the citizen applied for -- the consumer
    of the verified data in this exchange."""
    from sqlalchemy.orm import Session
    from app.core.persistence import SchemeCatalogRow, engine
    try:
        with Session(engine) as session:
            row = session.get(SchemeCatalogRow, application.get("serviceId"))
            return row.department if row else None
    except Exception:
        return None


def _department_name(provider_id: Optional[str], fallback: Optional[str] = None) -> str:
    from app.engine.departments import department_label, provider_department
    return department_label(provider_department(provider_id)) or fallback or "Department"


def interoperability_trace(application_id: str, requirement: dict, consumer: Optional[str], attempt_log: list[dict],
                           adapter_result: Optional[AdapterResult], requested_at: str) -> dict:
    label = requirement.get("label") or str(requirement.get("code", "")).replace("_", " ").title()
    steps = []

    def step(stage, title, status="info", at=None, **detail):
        steps.append({"at": at or requested_at, "stage": stage, "title": title, "status": status,
                      **{key: value for key, value in detail.items() if value is not None}})

    step("REQUEST", f"{consumer or 'Service'} application requested {label}", actor=consumer or "Citizen application", target="SANGAM")
    step("REQUIREMENT", f"SANGAM identified requirement {requirement.get('code')}", actor="SANGAM")
    authoritative = sum(1 for entry in attempt_log if entry.get("role") == "AUTHORITATIVE")
    step("REGISTRY", "Provider registry lookup: authorized providers ranked (authoritative first, then authorized fallbacks)", actor="SANGAM",
         providersConsidered=len(attempt_log), authoritativeConsidered=authoritative)
    fallback_announced = False
    for entry in attempt_log:
        department = _department_name(entry.get("providerId"), entry.get("provider"))
        at = entry.get("at")
        if entry.get("skipped"):
            step("PROVIDER_UNAVAILABLE", f"{department} unavailable — skipped (incident open)", "fail", at, provider=department)
            continue
        if entry.get("role") == "AUTHORIZED_FALLBACK" and not fallback_announced:
            fallback_announced = True
            step("FALLBACK_POLICY", f"Fallback policy evaluated — {department} is an authorized fallback for this requirement", "warn", at, provider=department)
        else:
            step("PROVIDER_SELECTED", f"{department} selected ({'authoritative source' if entry.get('role') == 'AUTHORITATIVE' else 'provider'})", "info", at, provider=department)
        step("API_REQUEST", f"SANGAM → {department} API request", "info", at, actor="SANGAM", target=department)
        if entry.get("success"):
            step("API_RESPONSE", f"{department} returned a record", "ok", entry.get("completedAt"), actor=department, target="SANGAM")
        elif entry.get("recordNotFound"):
            outcome = "details matched more than one person" if entry.get("lookupResult") == "AMBIGUOUS" else "no record"
            step("API_RESPONSE", f"{department}: {outcome} — continuing with the next authorized provider", "warn", entry.get("completedAt"), actor=department)
        else:
            step("API_RESPONSE", f"{department} request failed ({str(entry.get('errorCategory') or 'error').replace('_', ' ').lower()})", "fail", entry.get("completedAt"), actor=department)
    now = _now()
    status = requirement.get("status")
    match = requirement.get("identityMatch") or {}
    provenance = requirement.get("provenance") or {}
    if adapter_result is not None and adapter_result.success:
        category = (match.get("matchCategory") or "UNCHECKED").replace("_", " ").title()
        step("ENTITY_RESOLUTION", f"Entity resolution → {category} match", "ok" if match.get("decision", "AUTO_ACCEPT") == "AUTO_ACCEPT" else "fail", now,
             method=(match.get("departmentMatchMethod") or "").replace("_", " ").lower() or None, confidence=match.get("score"))
        if status in SUCCESS_STATUSES or status == "REJECTED":
            step("NORMALIZATION", f"Schema normalization → {len(requirement.get('canonical') or {})} canonical field(s)", "ok", now)
            step("VERIFICATION", f"{label} {'verified' if status in SUCCESS_STATUSES else 'failed validation'}", "ok" if status in SUCCESS_STATUSES else "fail", now)
    if status in SUCCESS_STATUSES:
        via = provenance.get("fallbackUsed")
        outcome, result_status = ("AUTO_FILLED_VIA_FALLBACK", "warn") if via else ("AUTO_FILLED", "ok")
        step("RESULT", "Auto-Fill completed via authorized fallback" if via else "Auto-Fill completed", result_status, now)
    elif requirement.get("errorCategory") == "IDENTITY_UNCONFIRMED":
        outcome = "NOT_ATTACHED"
        step("RESULT", "Record not attached — identity not confirmed with sufficient confidence", "fail", now)
    elif requirement.get("errorCategory") in _OUTAGE:
        outcome = "PENDING"
        step("RESULT", "Requirement pending — verification temporarily unavailable; citizen offered Retry and Upload", "fail", now)
    elif requirement.get("errorCategory") == "VALIDATION_ERROR":
        outcome = "NO_RECORD"
        step("RESULT", "No verified record in the connected departments — manual upload offered", "warn", now)
    else:
        outcome = "NOT_COMPLETED"
        step("RESULT", "Automatic verification not completed — manual upload offered", "fail", now)
    answered = next((entry for entry in attempt_log if entry.get("success")), None)
    target = _department_name(answered.get("providerId"), answered.get("provider")) if answered else None
    step("RETURN", f"SANGAM → {consumer or 'application'}: result returned to the application", "info", now, actor="SANGAM", target=consumer)
    return {"applicationId": application_id, "requirementCode": requirement.get("code"), "requirementLabel": label,
            "consumerDepartment": consumer, "targetDepartment": target, "startedAt": requested_at, "completedAt": now,
            "outcome": outcome, "fallbackUsed": bool(provenance.get("fallbackUsed")), "steps": steps}


def _after_exchange(application_id: str, requirement: dict, consumer: Optional[str]) -> None:
    """Post-commit side effects of one exchange: the department-to-department
    audit entry (source -> SANGAM -> target -> response -> verification ->
    result) and operational notifications for administrators."""
    trace = requirement.get("trace") or {}
    code = requirement.get("code")
    audit_bus.append(
        "SYSTEM", code, "Interoperability exchange through SANGAM", "SANGAM", "INTEROP_EXCHANGE",
        payload={"appId": application_id, "requirementCode": code, "sourceDepartment": consumer, "via": "SANGAM",
                 "targetDepartment": trace.get("targetDepartment"), "response": "RECORD" if trace.get("targetDepartment") else "NONE",
                 "verification": requirement.get("status"), "result": trace.get("outcome"), "fallbackUsed": trace.get("fallbackUsed")},
        correlation_id=application_id,
    )
    from app.core.notification_manager import notification_manager
    label = requirement.get("label") or code
    provenance = requirement.get("provenance") or {}
    if trace.get("outcome") == "AUTO_FILLED_VIA_FALLBACK":
        notification_manager.operational(
            "FALLBACK_ACTIVATED", "Authorized fallback used",
            f"{label} for {application_id} was verified by {trace.get('targetDepartment')} (authorized fallback) because the authoritative source could not answer.",
            dedupe_key=f"FALLBACK:{application_id}:{code}:{provenance.get('verifiedAt')}", severity="WARNING", app_id=application_id,
            target={"kind": "application", "applicationId": application_id, "providerId": provenance.get("providerId")})
    elif trace.get("outcome") == "PENDING":
        notification_manager.operational(
            "APPLICATION_BLOCKED", "Application waiting on an unavailable provider",
            f"{application_id} is waiting: {label} cannot be verified while its authorized providers are unavailable.",
            dedupe_key=f"BLOCKED:{application_id}:{code}", severity="WARNING", app_id=application_id,
            target={"kind": "application", "applicationId": application_id})
    elif trace.get("outcome") == "NOT_ATTACHED":
        match = requirement.get("identityMatch") or {}
        notification_manager.operational(
            "VERIFICATION_ISSUE", "Record not attached — identity not confirmed",
            f"{label} for {application_id}: a department record was found but did not match the applicant with enough confidence ({str(match.get('matchCategory') or 'low').lower()} match).",
            dedupe_key=f"VERIFICATION:{application_id}:{code}:{requirement.get('attempts')}", severity="WARNING", app_id=application_id,
            target={"kind": "application", "applicationId": application_id})
    elif requirement.get("errorCategory") in {"UPSTREAM_ERROR", "MALFORMED_RESPONSE", "AUTHORIZATION_ERROR", "AUTHENTICATION_ERROR"}:
        failed = next((entry for entry in reversed(requirement.get("fallbackAttempts") or []) if not entry.get("success") and not entry.get("skipped")), {})
        notification_manager.operational(
            "INTEGRATION_ERROR", "Integration error",
            f"A department API returned an error ({str(requirement.get('errorCategory')).replace('_', ' ').lower()}) while verifying {label} for {application_id}.",
            dedupe_key=f"INTEGRATION:{application_id}:{code}:{requirement.get('attempts')}", severity="CRITICAL", app_id=application_id,
            target={"kind": "provider", "providerId": failed.get("providerId"), "applicationId": application_id})


def _upsert_requirement_document(application_id: str, requirement_code: str, citizen_id: str, requirement: dict) -> Optional[dict]:
    """Create/update the document reference for a DOCUMENT/CERTIFICATE
    requirement only -- never for a RECORD/ATTRIBUTE requirement (no
    meaningless document rows), matching Phase 4/6B's exact rule."""
    if not is_document_requirement(requirement_code):
        return None
    status = requirement.get("status")
    if status not in {"VALIDATED", "REJECTED"}:
        return None

    from app.core.persistence import get_document, upsert_document

    document_id = _document_id(application_id, requirement_code)
    existing = get_document(document_id)
    if existing and existing.get("status") == "VALIDATED" and status != "VALIDATED":
        # Never let an unrelated later failure/rejection downgrade an
        # already-validated document (same guarantee artifact_retrieval.
        # _reconcile_document already gives the legacy dependency path).
        return existing

    canonical = requirement.get("canonical") or {}
    checksum = hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    reference_uri = f"provider-ref://{requirement.get('resultReference')}" if requirement.get("resultReference") else None
    document = {
        "documentId": document_id, "appId": application_id, "dependencyId": None,
        "requirementCode": requirement_code, "citizenId": citizen_id,
        "sourceType": _source_category_for_provider(requirement.get("providerId")),
        "providerId": requirement.get("providerId"), "documentType": requirement_code,
        "status": status, "checksum": checksum, "isSynthetic": True,
        "referenceUri": reference_uri,
        "validation": requirement.get("validation") or {"valid": status == "VALIDATED", "reasons": []},
        "canonical": canonical,
    }
    return upsert_document(document)


def fulfill_requirement(application: dict, requirement_code: str, citizen_id: str, consent_id: str, *, correlation_id: Optional[str] = None) -> dict:
    """The ACCEPT path: consent-gated, dynamic-discovery retrieval for
    exactly one requirement on one application, persisted through the
    PostgreSQL-authoritative application mutation gateway.

    Raises ``ConsentAuthorizationError`` (uncaught) if ``consent_id`` does not
    authorize this exact citizen/application/purpose -- no provider call
    happens in that case, matching the existing consent-gated dependency
    path's fail-closed behaviour.
    """
    application_id = application["appId"]
    if find_requirement(application, requirement_code) is None:
        raise KeyError(requirement_code)

    purpose = auto_fill_purpose(requirement_code)
    attempt_log: list[dict] = []
    requested_at = _now()

    def _operation() -> AdapterResult:
        result, log = _discover_and_retrieve(requirement_code, citizen_id, application_id, correlation_id, consent_id)
        attempt_log.extend(log)
        return result

    adapter_result = execute_with_persisted_authorization(
        citizen_id, CONSUMER, purpose, requested_attributes=[], service_id=application.get("serviceId"),
        application_id=application_id, consent_id=consent_id,
        operation=_operation,
    )

    _attach_identity_match(adapter_result, citizen_id)
    applied = []
    consumer = _consumer_department(application)

    def mutate(requirement: dict) -> None:
        applied.append(_apply_outcome(requirement, adapter_result, attempt_log))
        if applied[-1]:
            requirement["trace"] = interoperability_trace(application_id, requirement, consumer, attempt_log, adapter_result, requested_at)

    updated_application, updated_requirement = mutate_requirement_under_lock(application_id, requirement_code, mutate)
    if applied and applied[0]:
        _after_exchange(application_id, updated_requirement, consumer)
    if applied and applied[0]:
        # Only touch the document reference when this outcome was actually
        # applied. A stale/no-op outcome (the requirement was already
        # satisfied by a faster concurrent attempt or a manual upload by the
        # time this one reached the lock) must not re-derive a document from
        # this attempt's own (possibly empty, possibly different) canonical
        # data and silently overwrite what's already there -- see
        # test_requirement_resilience.py's stale-response tests.
        _upsert_requirement_document(application_id, requirement_code, citizen_id, updated_requirement)
    return updated_application


def _attach_identity_match(adapter_result: Optional[AdapterResult], citizen_id: str) -> None:
    """Entity resolution for a department record: compare the record's own
    identity fields (name, date of birth, phone, address -- each department
    keeps them its own way) with the citizen's identity in SANGAM. Done
    before taking the application lock (it reads the citizen master only)."""
    record = adapter_result.record if adapter_result is not None and adapter_result.success else None
    if not isinstance(record, dict) or not isinstance(record.get("raw"), dict):
        return
    from app.engine.entity_resolution import citizen_identity, match_category, match_department_record
    department_match = record.get("departmentMatch") or {}
    method = department_match.get("method")
    # The record's own identity fields win; the identity the department
    # matched on fills in what the record itself does not carry.
    compared = {**(department_match.get("identity") or {}), **record["raw"]}
    match = match_department_record(citizen_identity(citizen_id), compared, record.get("sourceSystem"))
    if match is None and method == "DEMOGRAPHIC":
        # Found by demographics but nothing to verify it with: never attach.
        match = {"status": "UNCERTAIN", "decision": "REVIEW", "confidenceLevel": "MEDIUM", "score": None, "matchedFields": [],
                 "fieldComparisons": [], "demographicAnchors": 0,
                 "explanation": "The department found a possible record, but it carries no identity details SANGAM could verify."}
    elif match is not None and method == "DEMOGRAPHIC" and match.get("decision") == "AUTO_ACCEPT" and not match.get("demographicAnchors"):
        # A demographic match must agree on date of birth or phone, not on a name alone.
        match = {**match, "status": "UNCERTAIN", "decision": "REVIEW", "confidenceLevel": "MEDIUM"}
    if match is not None:
        match["matchCategory"] = match_category(match, method)
        match["departmentMatchMethod"] = method
        adapter_result.metadata["identityMatch"] = match


def reject_auto_fill(application: dict, requirement_code: str, citizen_id: str) -> dict:
    """The REJECT path: no consent is created, no provider is called, no
    result is fabricated. A requirement already in a successful terminal
    state is left untouched (a rejection cannot undo an already-satisfied
    requirement); anything else moves to ACTION_REQUIRED so the citizen can
    see their decision was recorded, with Manual Upload remaining available.
    """
    application_id = application["appId"]
    if find_requirement(application, requirement_code) is None:
        raise KeyError(requirement_code)

    def mutate(requirement: dict) -> None:
        if requirement.get("status") in SUCCESS_STATUSES:
            return
        requirement["status"] = "ACTION_REQUIRED"
        requirement.pop("autoFillRequestedAt", None)

    updated_application, _ = mutate_requirement_under_lock(application_id, requirement_code, mutate)
    return updated_application


def mutate_requirement_under_lock(application_id: str, requirement_code: str, mutator, before_commit=None) -> tuple[dict, dict]:
    """Read the application's current requirements *inside* a PostgreSQL row
    lock, apply ``mutator`` to just the target requirement, and persist the
    full list back through the authoritative mutation gateway, all within
    one caller-owned transaction.

    This is required for correctness under ANY concurrent requirement-level
    write to the same application -- not just Auto-Fill against Auto-Fill,
    but also Auto-Fill racing a citizen's manual upload for a different
    requirement (``citizen_routes.upload_requirement_document`` uses this
    same helper for exactly that reason). ``mutate_application`` locks the
    row for its own write, but two concurrent callers that each read the
    requirements list *before* acquiring any lock (as a naive
    ``get_application`` + patch would) can each build a patch from a stale
    snapshot, and the second writer's patch silently discards the first
    writer's change (a classic lost update). Reading under the same lock
    that protects the write closes that window: the second caller's read
    happens only after the first caller's write has committed and released
    the lock, so it always builds its patch from the latest state.

    ``before_commit`` (optional) is called with the same session after the
    requirement write and before the commit, for a dependent write that must
    succeed or fail together with it; if it raises, nothing is committed.
    """
    from sqlalchemy.orm import Session
    from app.core.persistence import engine, get_application, mutate_application

    with Session(engine) as session:
        locked = get_application(application_id, for_update=True, session=session)
        if locked is None:
            raise KeyError(application_id)
        if locked.get("status") == SUBMITTED_APPLICATION_STATUS:
            # The same row lock that serializes concurrent requirement
            # writes against each other also serializes against a
            # concurrent submission (app.engine.submission.submit_application
            # takes this exact lock too) -- so this fresh, lock-protected
            # read is always accurate: if a submission committed anywhere
            # between this request's own provider call and this write, it is
            # visible here, and the mutation is refused rather than silently
            # applied to an application the citizen can no longer edit.
            session.commit()
            raise ApplicationSubmittedError(application_id)
        requirements = deepcopy(locked.get("requirements", []))
        requirement = find_requirement({"requirements": requirements}, requirement_code)
        if requirement is None:
            raise KeyError(requirement_code)
        mutator(requirement)
        updated_application = mutate_application(application_id, {"requirements": requirements}, session=session)
        if before_commit is not None:
            before_commit(session)
        session.commit()
        updated_requirement = find_requirement(updated_application, requirement_code)
        return updated_application, updated_requirement
