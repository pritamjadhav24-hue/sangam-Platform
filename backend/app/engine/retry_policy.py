"""Failure classification and provider fallback policy.

This sits on top of the existing, unchanged infrastructure: the adapter error
taxonomy (``app.engine.adapters.ERROR_CATEGORIES`` / ``RETRYABLE_CATEGORIES``),
the existing dependency attempt/maxAttempts bookkeeping
(``dependency_orchestrator.ensure_dependency`` / ``initiate_dependency``), and
the existing capability-driven provider registry
(``app.engine.registry.dependency_registry`` / ``select_dependency_provider``).

It does not introduce a second retry/job framework, a second provider
selection algorithm, or a new application/dependency status value. It adds
exactly two things the existing pieces don't already do on their own:

1. A single place that turns "dependency + its last error" into a retry
   decision (RETRY_SAME_PROVIDER / FALLBACK_PROVIDER / WAITING_RETRY_EXHAUSTED
   / NOT_RETRYABLE / NONE), for observability and for the fallback check below.
2. Provider fallback: once a dependency's *current* provider has exhausted its
   own attempts, check whether the existing capability registry has another
   eligible provider for the same requirement and, if so, re-point the
   dependency at it (resetting only that provider's own attempt counter).
   "Eligible" is determined purely by the existing requirement/capability/
   health data -- never a hardcoded department name or fallback chain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.engine.adapters import ERROR_CATEGORIES, RETRYABLE_CATEGORIES

RETRY_SAME_PROVIDER = "RETRY_SAME_PROVIDER"
FALLBACK_PROVIDER = "FALLBACK_PROVIDER"
WAITING_RETRY_EXHAUSTED = "WAITING_RETRY_EXHAUSTED"
NOT_RETRYABLE = "NOT_RETRYABLE"
NONE_OUTCOME = "NONE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_retryable_category(error_category: Optional[str]) -> bool:
    """Reuses the adapter layer's existing taxonomy; does not redefine it."""
    return error_category in RETRYABLE_CATEGORIES


def classify_dependency_failure(dependency: dict) -> dict:
    """Describe the dependency's current failure state for observability and
    for retry_decision(). Never mutates the dependency."""
    error_category = dependency.get("errorCategory")
    attempts = dependency.get("attempts", 0)
    max_attempts = dependency.get("maxAttempts", 3)
    retryable = is_retryable_category(error_category)
    exhausted = attempts >= max_attempts
    return {
        "errorCategory": error_category,
        "knownCategory": error_category in ERROR_CATEGORIES if error_category else False,
        "retryable": retryable,
        "attempts": attempts,
        "maxAttempts": max_attempts,
        "attemptsExhausted": exhausted,
    }


def retry_decision(dependency: dict, has_fallback_candidate: bool = False) -> str:
    """Pure decision function: same-provider retry / fallback / exhausted /
    not-retryable / none (dependency already resolved). Consent failures never
    reach here -- they raise before a dependency status is set."""
    if dependency.get("status") == "COMPLETED":
        return NONE_OUTCOME
    classification = classify_dependency_failure(dependency)
    if not classification["errorCategory"]:
        return NONE_OUTCOME
    if not classification["retryable"]:
        return NOT_RETRYABLE
    if not classification["attemptsExhausted"]:
        return RETRY_SAME_PROVIDER
    return FALLBACK_PROVIDER if has_fallback_candidate else WAITING_RETRY_EXHAUSTED


def find_fallback_candidate(requirement_code: str, current_provider_id: Optional[str] = None,
                             exclude_provider_ids: Optional[set] = None) -> Optional[dict]:
    """Look for another eligible, healthy provider for this requirement using
    the existing, unmodified capability registry. Returns None if none
    exists -- callers must then leave the dependency waiting, never invent a
    provider.

    ``exclude_provider_ids`` generalizes ``current_provider_id`` to a whole
    set, for a caller (an in-request fallback cascade) that must not
    re-select ANY provider already attempted this operation, not just the
    single most recent one.
    """
    from app.engine.adapters import integration_health
    from app.engine.registry import dependency_registry

    excluded = set(exclude_provider_ids or ())
    if current_provider_id:
        excluded.add(current_provider_id)
    candidates = [
        item for item in dependency_registry(integration_health())
        if item.get("requirementCode") == requirement_code
        and item.get("healthStatus") in {"AVAILABLE", "HEALTHY"}
        and item.get("providerId") not in excluded
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.get("priority", 100), item["provider"]))[0]


def attempt_provider_fallback(app: dict, requirement_code: str) -> bool:
    """If the dependency's current provider has exhausted its attempts,
    switch it to another eligible provider (if the existing registry has
    one) and reset only that provider's attempt counter so retries continue
    against the new provider. Returns True iff a fallback provider was
    selected. A dependency already COMPLETED, or one that still has retries
    left against its current provider, is left untouched.
    """
    dependency = next((item for item in app.get("dependencies", []) if item.get("requiredData") == requirement_code), None)
    if not dependency or dependency.get("status") == "COMPLETED":
        return False
    if dependency.get("attempts", 0) < dependency.get("maxAttempts", 3):
        return False

    candidate = find_fallback_candidate(requirement_code, dependency.get("providerId"))
    if not candidate:
        return False

    from app.core.audit_bus import audit_bus
    from app.core.event_bus import event_bus

    previous_provider = dependency.get("providerId")
    dependency.update({
        "provider": candidate["provider"],
        "providerId": candidate.get("providerId", candidate["provider"]),
        "providerService": candidate["serviceId"],
        "serviceName": candidate["serviceName"],
        "adapter": candidate["adapter"],
        "attempts": 0,
        "status": "WAITING_FOR_DEPENDENCY",
        "providerStatus": candidate.get("healthStatus", "AVAILABLE"),
        "lastError": None,
        "errorCategory": None,
        "updatedAt": _now(),
        "providerSelection": {
            "requirementCode": requirement_code, "requiredService": candidate["requiredService"],
            "provider": candidate["provider"], "adapter": candidate["adapter"], "serviceId": candidate["serviceId"],
            "reason": "Fallback: previous provider exhausted its attempts", "healthStatus": candidate.get("healthStatus", "AVAILABLE"),
            "selectedAt": _now(), "previousProviderId": previous_provider,
        },
    })
    event_bus.publish("PROVIDER_FALLBACK_SELECTED", {
        "appId": app["appId"], "dependencyId": dependency["dependencyId"], "requiredData": requirement_code,
        "previousProviderId": previous_provider, "newProviderId": dependency["providerId"],
    })
    audit_bus.append("SYSTEM", "PROVIDER_FALLBACK", "Switched to an alternate eligible provider after retry exhaustion",
                      dependency["provider"], "FALLBACK", app.get("consentId"),
                      payload={"dependencyId": dependency["dependencyId"], "previousProviderId": previous_provider, "newProviderId": dependency["providerId"]},
                      correlation_id=app["appId"])
    return True
