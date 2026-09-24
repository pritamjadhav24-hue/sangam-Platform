"""Read-only Admin aggregations: analytics/reports, the scheme/requirement
catalogue and the effective access model.

Everything here is derived on read from existing persisted state
(ApplicationRow, ProviderJobRow, ProviderIncidentRow, SchemeCatalogRow,
SchemeRequirementRow, RequirementCatalogRow), the existing capability
registry (dependency_registry) and the existing live audit ledger. Nothing
is written, cached, estimated or back-filled.
"""
from __future__ import annotations

import inspect
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.persistence import (
    ApplicationRow, ProviderIncidentRow, ProviderJobRow, ProviderRow, RequirementCatalogRow,
    SchemeCatalogRow, SchemeRequirementRow, engine,
)

SUCCESS_STATUSES = {"VALIDATED", "RETRIEVED", "USER_OVERRIDDEN", "FOUND"}
ACTION_STATUSES = {"ACTION_REQUIRED", "FAILED", "REJECTED"}
OFFICER_STATUSES = {"WAITING_FOR_OFFICER", "CONFLICT_DETECTED"}
OUTCOMES = ("automaticallyVerified", "manuallyFulfilled", "citizenActionRequired",
            "officerReviewRequired", "retryInProgress", "processing")
# Below this many distinct days of activity a trend line would be a single
# point or two -- shown as "limited data" rather than drawn as a trend.
MIN_TREND_DAYS = 2


def _is_manual(requirement: dict) -> bool:
    return bool(requirement.get("documentId")) or requirement.get("fulfillmentMethod") == "MANUAL_UPLOAD"


def classify_application_outcome(app: dict) -> str:
    """One mutually-exclusive outcome bucket per application, derived from
    requirement-level data (not the coarse application status alone)."""
    status = app.get("status", "DRAFT")
    requirements = app.get("requirements", [])
    if status in OFFICER_STATUSES:
        return "officerReviewRequired"
    if status == "VERIFICATION_FAILED" or any(r.get("status") in ACTION_STATUSES for r in requirements):
        return "citizenActionRequired"
    if any(r.get("status") == "WAITING" for r in requirements):
        return "retryInProgress"
    fulfilled = [r for r in requirements if r.get("status") in SUCCESS_STATUSES]
    if requirements and len(fulfilled) == len(requirements):
        return "manuallyFulfilled" if any(_is_manual(r) for r in fulfilled) else "automaticallyVerified"
    return "processing"


def _parse_ts(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date '{value}'; expected YYYY-MM-DD.")


def _in_range(moment: Optional[datetime], start: Optional[date], end: Optional[date]) -> bool:
    if start is None and end is None:
        return True
    if moment is None:
        return False
    day = moment.date()
    return (start is None or day >= start) and (end is None or day <= end)


def _trend(points: list[Optional[datetime]]) -> dict:
    days = Counter(p.date().isoformat() for p in points if p is not None)
    series = [{"date": day, "count": days[day]} for day in sorted(days)]
    return {"series": series, "limited": len(series) < MIN_TREND_DAYS}


def _requirement_touches_provider(requirement: dict, provider_keys: set[str]) -> bool:
    if requirement.get("providerId") in provider_keys:
        return True
    return any(a.get("providerId") in provider_keys or a.get("provider") in provider_keys
               for a in requirement.get("fallbackAttempts") or [])


def analytics_report(*, start: Optional[str] = None, end: Optional[str] = None, status: Optional[str] = None,
                     outcome: Optional[str] = None, provider: Optional[str] = None,
                     requirement: Optional[str] = None, incident_status: Optional[str] = None) -> dict:
    from app.core.audit_bus import audit_bus
    from app.engine.adapters import integration_health

    start_day, end_day = _parse_day(start), _parse_day(end)
    if outcome and outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome '{outcome}'.")

    with Session(engine) as session:
        provider_keys: set[str] = set()
        if provider:
            row = session.get(ProviderRow, provider)
            if row is None:
                raise LookupError(f"Unknown provider '{provider}'.")
            provider_keys = {row.provider_id, row.name}

        # --- Applications (filtered server-side) ---
        applications = []
        for row in session.query(ApplicationRow).all():
            payload = dict(row.payload or {})
            created = _parse_ts(row.created_at) or _parse_ts(payload.get("createdAt"))
            if not _in_range(created, start_day, end_day):
                continue
            if status and status.upper() != "ALL" and (row.status or payload.get("status")) != status.upper():
                continue
            requirements = payload.get("requirements", [])
            if requirement:
                requirements = [r for r in requirements if r.get("code") == requirement]
                if not requirements:
                    continue
            if provider_keys:
                # Requirement statistics are scoped to what this provider
                # actually handled; the application-level outcome still
                # reflects the whole application.
                requirements = [r for r in requirements if _requirement_touches_provider(r, provider_keys)]
                if not requirements:
                    continue
            app_outcome = classify_application_outcome(payload)
            if outcome and app_outcome != outcome:
                continue
            updated = _parse_ts(row.updated_at) or _parse_ts(payload.get("updatedAt")) or created
            applications.append({"appId": row.app_id, "status": row.status or payload.get("status"),
                                 "outcome": app_outcome, "createdAt": created, "updatedAt": updated,
                                 "requirements": requirements})

        outcome_counts = {key: 0 for key in OUTCOMES}
        status_counts: Counter = Counter()
        for app in applications:
            outcome_counts[app["outcome"]] += 1
            status_counts[app["status"]] += 1

        # --- Requirement fulfillment ---
        req_counts = {"total": 0, "fulfilledAutomatically": 0, "fulfilledManually": 0, "pending": 0,
                      "actionRequired": 0, "retrying": 0, "failed": 0, "fallbackUsed": 0}
        by_requirement: dict[str, Counter] = defaultdict(Counter)
        fulfillment_points = []
        for app in applications:
            for r in app["requirements"]:
                code, r_status = r.get("code"), r.get("status")
                req_counts["total"] += 1
                by_requirement[code]["total"] += 1
                if r_status in SUCCESS_STATUSES:
                    key = "fulfilledManually" if _is_manual(r) else "fulfilledAutomatically"
                    # No per-requirement fulfillment timestamp is persisted
                    # ("verifiedOn" is the certificate's validity date, not
                    # when SANGAM verified it), so fulfillment is dated by
                    # the application's last update -- labelled as such.
                    fulfillment_points.append(app["updatedAt"])
                elif r_status == "ACTION_REQUIRED":
                    key = "actionRequired"
                elif r_status == "WAITING":
                    key = "retrying"
                elif r_status in {"FAILED", "REJECTED"}:
                    key = "failed"
                else:
                    key = "pending"
                req_counts[key] += 1
                by_requirement[code][key] += 1
                if r.get("isFallback"):
                    req_counts["fallbackUsed"] += 1
                    by_requirement[code]["fallbackUsed"] += 1

        # --- Provider jobs (filtered by date/provider; requirement filter
        # does not apply -- jobs carry no requirement code) ---
        jobs = []
        for job in session.query(ProviderJobRow).all():
            created = _parse_ts(job.created_at)
            if not _in_range(created, start_day, end_day):
                continue
            if provider_keys and job.provider_id not in provider_keys:
                continue
            jobs.append((job, created))
        job_status = Counter(job.status for job, _ in jobs)
        failure_points = [created for job, created in jobs if job.status in {"FAILED", "DEAD_LETTER"}]

        # --- Incidents ---
        incidents = []
        provider_names = {p.provider_id: p.name for p in session.query(ProviderRow).all()}
        for incident in session.query(ProviderIncidentRow).all():
            if not _in_range(_parse_ts(incident.detected_at), start_day, end_day):
                continue
            if provider_keys and incident.provider_system not in provider_keys:
                continue
            if incident_status and incident.status != incident_status.upper():
                continue
            incidents.append(incident)

    health = integration_health()
    health_status = Counter(item.get("status") for item in health)
    healthy = health_status.get("AVAILABLE", 0) + health_status.get("HEALTHY", 0)
    down = health_status.get("UNAVAILABLE", 0)

    replay_entries = [e for e in audit_bus.entries if e.get("action") == "REPLAY"
                      and (not provider_keys or e.get("source") in provider_keys)
                      and _in_range(_parse_ts(e.get("when")), start_day, end_day)]
    automatic_replays = [e for e in replay_entries if "automatically" in (e.get("why") or "")]

    return {
        "filters": {"start": start, "end": end, "status": status, "outcome": outcome, "provider": provider,
                    "requirement": requirement, "incidentStatus": incident_status},
        "applications": {
            "total": len(applications),
            "submitted": status_counts.get("SUBMITTED", 0),
            "byStatus": dict(status_counts),
            **outcome_counts,
            "appIds": [a["appId"] for a in applications][:200],
        },
        "requirements": {
            **req_counts,
            "byRequirement": [{"requirementCode": code, **dict(counts)} for code, counts in sorted(by_requirement.items())],
        },
        "providers": {
            "registered": len(health),
            "healthy": healthy,
            "down": down,
            "degraded": len(health) - healthy - down,
            "jobs": {
                "total": len(jobs),
                "byStatus": dict(job_status),
                "retries": sum(max((job.attempt or 0) - 1, 0) for job, _ in jobs),
                "deadLetter": job_status.get("DEAD_LETTER", 0),
                "failed": job_status.get("FAILED", 0),
            },
            "incidents": {
                "total": len(incidents),
                "open": sum(1 for i in incidents if i.status == "OPEN"),
                "resolved": sum(1 for i in incidents if i.status != "OPEN"),
                "byProvider": dict(Counter(i.provider_system for i in incidents)),
            },
            "replays": {"total": len(replay_entries), "automaticRecovery": len(automatic_replays),
                        "manual": len(replay_entries) - len(automatic_replays)},
            "fallbackUsed": req_counts["fallbackUsed"],
        },
        "trends": {
            "applications": _trend([a["createdAt"] for a in applications]),
            "fulfillment": _trend(fulfillment_points),
            "providerFailures": _trend(failure_points),
            "incidents": _trend([_parse_ts(i.detected_at) for i in incidents]),
            "recovery": _trend([_parse_ts(e.get("when")) for e in replay_entries]),
        },
        "providerNames": provider_names,
    }


# ---------------------------------------------------------------------------
# Scheme / requirement catalogue
# ---------------------------------------------------------------------------

def _requirement_vocabulary(session) -> dict[str, dict]:
    return {row.requirement_code: {"name": row.name, "category": row.category, "dataType": row.data_type,
                                   "description": row.description, "active": row.active}
            for row in session.query(RequirementCatalogRow).all()}


def _eligible_providers_by_requirement() -> dict[str, list[dict]]:
    from app.engine.adapters import integration_health
    from app.engine.registry import dependency_registry

    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in dependency_registry(integration_health()):
        grouped[entry["requirementCode"]].append({
            "providerId": entry.get("providerId"), "provider": entry.get("provider"),
            "priority": entry.get("priority", 100), "healthStatus": entry.get("healthStatus"),
            "serviceId": entry.get("serviceId"), "serviceName": entry.get("serviceName"),
        })
    for code in grouped:
        grouped[code].sort(key=lambda item: (item["priority"], item["provider"] or ""))
    return grouped


def _application_counts_by_scheme(session) -> Counter:
    counts: Counter = Counter()
    for row in session.query(ApplicationRow).all():
        payload = row.payload or {}
        scheme = payload.get("serviceId") or payload.get("schemeId")
        if scheme:
            counts[scheme] += 1
    return counts


def scheme_catalogue() -> list[dict]:
    providers_by_requirement = _eligible_providers_by_requirement()
    with Session(engine) as session:
        app_counts = _application_counts_by_scheme(session)
        result = []
        for scheme in session.query(SchemeCatalogRow).order_by(SchemeCatalogRow.name).all():
            requirements = session.query(SchemeRequirementRow).filter_by(scheme_id=scheme.scheme_id).all()
            codes = [r.requirement_code for r in requirements]
            payload = scheme.payload or {}
            result.append({
                "schemeId": scheme.scheme_id,
                "name": scheme.name,
                "department": scheme.department,
                "category": payload.get("category"),
                "active": scheme.active,
                "synthetic": bool(payload.get("synthetic", False)),
                "requirementCount": len(codes),
                "mandatoryCount": sum(1 for r in requirements if r.mandatory),
                "providerCoverage": sum(1 for code in codes if providers_by_requirement.get(code)),
                "applicationCount": app_counts.get(scheme.scheme_id, 0),
            })
        return result


def scheme_detail(scheme_id: str) -> Optional[dict]:
    providers_by_requirement = _eligible_providers_by_requirement()
    with Session(engine) as session:
        scheme = session.get(SchemeCatalogRow, scheme_id)
        if scheme is None:
            return None
        vocabulary = _requirement_vocabulary(session)
        payload = scheme.payload or {}
        requirements = []
        for row in session.query(SchemeRequirementRow).filter_by(scheme_id=scheme_id).order_by(SchemeRequirementRow.id).all():
            meta = row.payload or {}
            vocab = vocabulary.get(row.requirement_code)
            eligible = providers_by_requirement.get(row.requirement_code, [])
            requirements.append({
                "requirementCode": row.requirement_code,
                "label": row.label,
                "name": vocab["name"] if vocab else None,
                "description": vocab["description"] if vocab else None,
                "category": vocab["category"] if vocab else None,
                "dataType": vocab["dataType"] if vocab else meta.get("dataType"),
                "inRequirementCatalog": vocab is not None,
                "mandatory": row.mandatory,
                "requirementType": meta.get("requirementType"),
                # The capability a provider must register to satisfy this
                # requirement is the requirement code itself -- that is how
                # provider_capability_snapshot() keys capabilities.
                "capability": row.requirement_code,
                "eligibleProviders": eligible,
                "manualUploadOnly": not eligible,
            })
        return {
            "schemeId": scheme.scheme_id,
            "name": scheme.name,
            "department": scheme.department,
            "active": scheme.active,
            "synthetic": bool(payload.get("synthetic", False)),
            "category": payload.get("category"),
            "description": payload.get("description"),
            "benefits": payload.get("benefits"),
            "eligibility": payload.get("eligibility"),
            "applicationWindow": payload.get("applicationWindow"),
            "applicationCount": _application_counts_by_scheme(session).get(scheme_id, 0),
            "requirements": requirements,
        }


# ---------------------------------------------------------------------------
# Profile / effective access model
# ---------------------------------------------------------------------------

def _route_roles(route) -> Optional[tuple]:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None
    for dependency in dependant.dependencies:
        call = dependency.call
        if getattr(call, "__name__", "") != "dependency":
            continue
        roles = inspect.getclosurevars(call).nonlocals.get("roles")
        if roles:
            return tuple(roles)
    return None


def effective_access_model(routes) -> dict:
    """The access model actually enforced by the running application,
    derived by introspecting every route's require_roles() dependency --
    not a hand-written permission list that could drift from the code."""
    areas: dict[str, dict] = {}
    for route in routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        roles = _route_roles(route)
        area = "/".join(path.split("/")[:3])
        bucket = areas.setdefault(area, {"area": area, "endpoints": 0, "public": 0, "byRole": Counter()})
        for method in sorted(getattr(route, "methods", []) or []):
            if method == "HEAD":
                continue
            bucket["endpoints"] += 1
            if roles is None:
                bucket["public"] += 1
            else:
                for role in roles:
                    bucket["byRole"][role] += 1
    result = []
    for area in sorted(areas):
        bucket = areas[area]
        result.append({"area": area, "endpoints": bucket["endpoints"], "public": bucket["public"],
                       "byRole": dict(bucket["byRole"])})
    return {"roles": ["CITIZEN", "OFFICER", "ADMIN"], "areas": result, "mutablePermissions": False}
