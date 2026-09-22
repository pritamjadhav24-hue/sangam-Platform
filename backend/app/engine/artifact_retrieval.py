"""Generic document/artifact retrieval and lifecycle layer.

Sits on top of the existing requirement -> provider -> adapter -> consent ->
dependency architecture (Phases 1-3), unchanged. Nothing here duplicates the
provider registry, the adapter boundary, the consent implementation, or the
workflow engine: it calls them as-is (``ensure_dependency``,
``initiate_dependency``, ``execute_with_persisted_authorization`` indirectly
via those two) and adds one additive concept -- a ``DocumentRow`` reference
that tracks the lifecycle of an *artifact* (as opposed to a plain structured
value) for one requirement on one application.

Not every requirement is a document requirement. Whether a requirement
produces a trackable document reference is read from the existing
``requirements`` catalog (``RequirementCatalogRow.data_type``): DOCUMENT and
CERTIFICATE requirements get a document reference; RECORD/ATTRIBUTE
requirements keep behaving exactly as they did in Phase 3 (no document row).

Source priority (trusted digital repository vs. department provider) is not
a new selection algorithm: it is the *existing* priority-ordered capability
selection (``select_dependency_provider`` / ``dependency_registry``,
untouched) plus one optional metadata field on a provider's own catalog
payload (``sourceCategory``). A future DigiLocker/API-Setu-style provider
simply gets registered with a lower ``priority`` number and
``sourceCategory: "TRUSTED_DIGITAL_REPOSITORY"``; it would then be picked
first automatically, with no orchestration code changes. No such provider is
registered by this phase.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

DOCUMENT_DATA_TYPES = frozenset({"DOCUMENT", "CERTIFICATE"})
DEFAULT_SOURCE_CATEGORY = "DEPARTMENT_PROVIDER"
MAX_UPLOAD_TEXT_BYTES = 200_000
ALLOWED_UPLOAD_CONTENT_TYPES = frozenset({"text/plain", "application/json"})


def requirement_data_type(requirement_code: str) -> str:
    """Read the catalogued data type for a requirement; defaults to RECORD
    (non-document) when the requirement isn't catalogued, so document
    behaviour is strictly opt-in and never assumed."""
    from sqlalchemy.orm import Session
    from app.core.persistence import RequirementCatalogRow, engine
    with Session(engine) as session:
        row = session.get(RequirementCatalogRow, requirement_code)
    return row.data_type if row else "RECORD"


def is_document_requirement(requirement_code: str) -> bool:
    return requirement_data_type(requirement_code) in DOCUMENT_DATA_TYPES


def _source_category_for_provider(provider_id: Optional[str]) -> str:
    if not provider_id:
        return DEFAULT_SOURCE_CATEGORY
    from sqlalchemy.orm import Session
    from app.core.persistence import ProviderRow, engine
    with Session(engine) as session:
        provider = session.get(ProviderRow, provider_id)
    if not provider:
        return DEFAULT_SOURCE_CATEGORY
    return (provider.payload or {}).get("sourceCategory", DEFAULT_SOURCE_CATEGORY)


def _document_id(app_id: str, requirement_code: str) -> str:
    return f"DOC-{app_id}-{requirement_code}"


TERMINAL_VALID_STATUSES = frozenset({"VALIDATED"})


def _reconcile_document(app: dict, requirement_code: str, dependency: dict, *,
                         source_type_override: Optional[str] = None,
                         checksum: Optional[str] = None,
                         retry_decision_value: Optional[str] = None,
                         extra_payload: Optional[dict] = None) -> Optional[dict]:
    """Create or update the document reference for one requirement from the
    dependency's current state. Safe to call repeatedly -- the document id is
    deterministic per (app, requirement), so retries/later responses update
    the same row rather than creating duplicates (recoverable waiting state).

    Consistency guarantees (hardened in Phase 5): a document already
    VALIDATED is never downgraded by a later, unrelated failed attempt, and
    its checksum/reference are preserved when a reconciliation call doesn't
    carry a fresher one of its own.
    """
    if not is_document_requirement(requirement_code):
        return None
    from app.core.persistence import get_document, upsert_document

    document_id = _document_id(app["appId"], requirement_code)
    existing = get_document(document_id)
    if existing and existing.get("status") in TERMINAL_VALID_STATUSES and dependency.get("status") != "COMPLETED":
        # The dependency reports a fresh, unrelated failure (e.g. a stray
        # retry after the requirement was already satisfied), but this
        # document is already a validated artifact. Never let a failure
        # state overwrite a valid result -- return it unchanged.
        return existing

    requirement = next((item for item in app.get("requirements", []) if item["code"] == requirement_code), None)
    completed = dependency.get("status") == "COMPLETED"
    source_type = source_type_override or _source_category_for_provider(dependency.get("providerId"))
    validation = (requirement or {}).get("validation") or {"valid": False, "reasons": ["Artifact not yet retrieved"]}
    status = ("VALIDATED" if validation.get("valid") else "REJECTED") if completed else "WAITING_FOR_RESPONSE"
    resolved_checksum = checksum if checksum is not None else (existing.get("checksum") if existing else None)
    resolved_reference_uri = (f"provider://{dependency.get('providerId')}/{dependency.get('resultReference')}"
                               if completed and dependency.get("resultReference")
                               else (existing.get("referenceUri") if existing else None))
    document = {
        "documentId": document_id,
        "appId": app["appId"],
        "dependencyId": dependency.get("dependencyId"),
        "requirementCode": requirement_code,
        "citizenId": app.get("citizenId"),
        "sourceType": source_type,
        "providerId": dependency.get("providerId"),
        "documentType": requirement_code,
        "status": status,
        "checksum": resolved_checksum,
        "isSynthetic": True,
        "referenceUri": resolved_reference_uri,
        "validation": validation,
        "canonical": (requirement or {}).get("canonical"),
        "lastError": dependency.get("lastError"),
        "errorCategory": dependency.get("errorCategory"),
        "attempts": dependency.get("attempts"),
        "provider": dependency.get("provider"),
        "retryDecision": retry_decision_value,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        **(extra_payload or {}),
    }
    return upsert_document(document)


def retrieve_artifact(app: dict, requirement_code: str, citizen_id: str, *, correlation_id: Optional[str] = None) -> dict:
    """requirement -> discovery -> consent -> adapter -> department API ->
    schema mapping -> canonical/validation -> dependency result -> document
    reference. ``ConsentAuthorizationError`` propagates uncaught (fail
    closed); no document reference is written for a denied/missing consent.

    On a retryable failure whose current provider has exhausted its own
    attempts, this checks the existing capability registry for another
    eligible provider (see retry_policy.attempt_provider_fallback) and, if
    one exists, retries once against it in the same call -- otherwise the
    dependency/document are left in a recoverable waiting state.
    """
    from app.engine import retry_policy
    from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency

    dependency = ensure_dependency(app, requirement_code)
    result = initiate_dependency(citizen_id, app, requirement_code)

    has_fallback = (not result.get("success")) and bool(
        retry_policy.find_fallback_candidate(requirement_code, dependency.get("providerId"))
    )
    decision = retry_policy.retry_decision(dependency, has_fallback_candidate=has_fallback)

    if decision == retry_policy.FALLBACK_PROVIDER and retry_policy.attempt_provider_fallback(app, requirement_code):
        result = initiate_dependency(citizen_id, app, requirement_code)
        decision = retry_policy.retry_decision(dependency)

    document = _reconcile_document(app, requirement_code, dependency, retry_decision_value=decision)
    return {
        "dependency": result, "document": document,
        "isDocumentRequirement": is_document_requirement(requirement_code),
        "retryDecision": decision,
    }


def validate_upload_metadata(artifact: dict) -> dict:
    """Basic integrity/acceptability checks for an uploaded artifact -- this
    is distinct from validation_engine.validate (which checks a canonical
    record's field-level correctness): this checks the raw artifact itself
    before it is ever turned into a dependency result."""
    reasons = []
    if not artifact.get("title"):
        reasons.append("Artifact title is required")
    content = artifact.get("content")
    if not content:
        reasons.append("Artifact content is required")
    elif isinstance(content, str) and len(content.encode("utf-8")) > MAX_UPLOAD_TEXT_BYTES:
        reasons.append("Artifact content exceeds the maximum allowed size")
    content_type = artifact.get("contentType", "text/plain")
    if content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        reasons.append(f"Unsupported artifact content type: {content_type}")
    return {"valid": not reasons, "reasons": reasons}


def submit_citizen_upload(app: dict, requirement_code: str, citizen_id: str, artifact: dict, *, correlation_id: Optional[str] = None) -> dict:
    """Citizen-upload ingestion boundary.

    Validates the artifact, then feeds it through the *existing* dependency
    completion path (the same authorized_adapter_result seam the async
    provider-job worker already uses) so a citizen-supplied artifact updates
    the dependency/workflow through the one existing mutation architecture --
    never a second state machine. A requirement is never marked complete
    without validation: an invalid artifact is rejected before any dependency
    mutation happens.
    """
    if app.get("citizenId") != citizen_id:
        raise ValueError("A citizen may only upload artifacts for their own application")

    integrity = validate_upload_metadata(artifact)
    if not integrity["valid"]:
        return {"status": "REJECTED", "reasons": integrity["reasons"], "document": None}

    from app.engine.adapters import AdapterResult
    from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency

    dependency = ensure_dependency(app, requirement_code)
    document_id = _document_id(app["appId"], requirement_code)
    content = str(artifact["content"])
    content_type = artifact.get("contentType", "text/plain")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    canonical = {"title": artifact["title"], "contentType": content_type, "checksum": checksum}
    record = {
        "id": document_id,
        "status": "UPLOADED",
        "synthetic": True,
        "sourceSystem": "Citizen Upload",
        "canonical": canonical,
        "raw": {"title": artifact["title"], "contentType": content_type, "checksum": checksum},
    }
    adapter_result = AdapterResult(
        record, provider="Citizen Upload", operation="upload",
        correlation_id=correlation_id or app.get("appId"), success=True,
        metadata={"providerId": "CITIZEN-UPLOAD"},
    )
    result = initiate_dependency(citizen_id, app, requirement_code, async_override=True, authorized_adapter_result=adapter_result)
    document = _reconcile_document(
        app, requirement_code, dependency, source_type_override="CITIZEN_UPLOAD", checksum=checksum,
        extra_payload={"title": artifact["title"], "contentType": content_type, "contentPreview": content[:2000]},
    )
    return {"status": "ACCEPTED" if result.get("success") else "PENDING", "document": document, "dependencyResult": result}
