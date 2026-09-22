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

from app.engine import retry_policy
from app.engine.adapters import AdapterResult, integration_health, request_registered_service
from app.engine.artifact_retrieval import _source_category_for_provider, is_document_requirement
from app.engine.consent_manager import CONSUMER, execute_with_persisted_authorization
from app.engine.registry import select_dependency_provider
from app.engine.validation_engine import validate

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


def _discover_and_retrieve(requirement_code: str, citizen_id: str, application_id: str, correlation_id: Optional[str]) -> AdapterResult:
    """Fresh, server-side-only provider discovery + adapter call for exactly
    this requirement. The frontend has no way to influence which provider is
    selected -- this function takes no provider/department input at all."""
    selected = select_dependency_provider(requirement_code, integration_health())
    if not selected:
        return AdapterResult(None, correlation_id=correlation_id, error_category="CONFIGURATION_ERROR", success=False, retryable=False)
    return request_registered_service(
        selected["serviceId"], citizen_id, requirement_code=requirement_code,
        correlation_id=correlation_id, idempotency_key=f"{application_id}:{requirement_code}",
    )


def _apply_outcome(requirement: dict, adapter_result: Optional[AdapterResult]) -> bool:
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
    record = adapter_result.record if adapter_result else None
    if record:
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
    adapter_result = execute_with_persisted_authorization(
        citizen_id, CONSUMER, purpose, requested_attributes=[], service_id=application.get("serviceId"),
        application_id=application_id, consent_id=consent_id,
        operation=lambda: _discover_and_retrieve(requirement_code, citizen_id, application_id, correlation_id),
    )

    applied = []

    def mutate(requirement: dict) -> None:
        applied.append(_apply_outcome(requirement, adapter_result))

    updated_application, updated_requirement = mutate_requirement_under_lock(application_id, requirement_code, mutate)
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


def mutate_requirement_under_lock(application_id: str, requirement_code: str, mutator) -> tuple[dict, dict]:
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
        session.commit()
        updated_requirement = find_requirement(updated_application, requirement_code)
        return updated_application, updated_requirement
