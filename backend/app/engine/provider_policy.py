"""Provider authorization policy: priority is not capability is not authorization.

* Capability    -- the registry says a provider *can* answer a requirement
                   (an enabled ProviderCapabilityRow).
* Authorization -- whether it is *allowed* to, and in which role:
                   AUTHORITATIVE       the source of record for the requirement;
                   AUTHORIZED_FALLBACK allowed to answer only when no
                                       authoritative source can (explicit policy);
                   NOT_AUTHORIZED      never selected, whatever its priority.
* Priority      -- ordering *among* providers already authorized for a role.

Authorization is never inferred from priority. It is read, in order, from:
1. the capability row itself (``payload["authorization"]``) -- data an
   administrator can change without touching code;
2. the registered provider definition the row was seeded from (the same
   definitions that created the registry), for rows created before this
   policy existed -- so existing registries need no data migration;
3. otherwise the capability is NOT_AUTHORIZED (fail closed).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

AUTHORITATIVE = "AUTHORITATIVE"
AUTHORIZED_FALLBACK = "AUTHORIZED_FALLBACK"
NOT_AUTHORIZED = "NOT_AUTHORIZED"
ROLE_LABELS = {AUTHORITATIVE: "Authoritative source", AUTHORIZED_FALLBACK: "Authorized fallback", NOT_AUTHORIZED: "Not authorized"}


def policy(authoritative: bool = False, fallback_authorized: bool = False, basis: Optional[str] = None) -> dict:
    return {"authoritative": bool(authoritative), "fallbackAuthorized": bool(fallback_authorized), **({"basis": basis} if basis else {})}


AUTHORITATIVE_POLICY = policy(authoritative=True, basis="Department of record for this requirement")


@lru_cache(maxsize=1)
def _registered_policies() -> dict[str, dict]:
    """capability id -> policy, from the provider definitions that seed the registry."""
    from app.core.persistence import DEPARTMENT_SANDBOX_PROVIDERS
    from app.engine.registry import DEPENDENCY_SERVICES

    policies = {}
    for definition in DEPENDENCY_SERVICES:
        provider_id = definition["provider"].upper().replace(" ", "-")
        policies[f"{provider_id}:{definition['requirementCode']}"] = definition.get("authorization") or AUTHORITATIVE_POLICY
    for entry in DEPARTMENT_SANDBOX_PROVIDERS:
        policies[f"{entry['providerId']}:{entry['requirementCode']}"] = entry.get("authorization") or AUTHORITATIVE_POLICY
    return policies


def role_of(declared: Optional[dict]) -> str:
    if not isinstance(declared, dict):
        return NOT_AUTHORIZED
    if declared.get("authoritative"):
        return AUTHORITATIVE
    if declared.get("fallbackAuthorized"):
        return AUTHORIZED_FALLBACK
    return NOT_AUTHORIZED


def capability_authorization(capability_id: str, payload: Optional[dict]) -> dict:
    """The effective authorization of one capability, and where it came from."""
    explicit = (payload or {}).get("authorization")
    if isinstance(explicit, dict):
        declared, source = explicit, "REGISTRY"
    else:
        declared = _registered_policies().get(capability_id)
        source = "REGISTERED_DEFINITION" if declared else "UNDECLARED"
    role = role_of(declared)
    return {"role": role, "label": ROLE_LABELS[role], "authoritative": role == AUTHORITATIVE,
            "fallbackAuthorized": role == AUTHORIZED_FALLBACK, "source": source, "basis": (declared or {}).get("basis")}


def item_role(item: dict) -> str:
    """Role of a registry item (a dependency_registry / capability snapshot entry)."""
    authorization = item.get("authorization")
    if isinstance(authorization, dict) and authorization.get("role"):
        return authorization["role"]
    return NOT_AUTHORIZED


def is_selectable(item: dict) -> bool:
    return item_role(item) in {AUTHORITATIVE, AUTHORIZED_FALLBACK}


def selection_key(item: dict) -> tuple:
    """Authoritative sources before authorized fallbacks; priority orders
    providers only within the same role."""
    return (0 if item_role(item) == AUTHORITATIVE else 1, item.get("priority", 100), item.get("provider") or "")
