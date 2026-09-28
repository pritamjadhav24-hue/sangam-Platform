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


# ---------------------------------------------------------------------------
# Provider incident impact
# ---------------------------------------------------------------------------
# Incident -> unavailable provider -> the requirement codes it serves ->
# requirement operations inside the incident window (or, while it is open,
# unfulfilled requirements with no other healthy provider) -> application ->
# citizen. A citizen is affected only through such a concrete requirement,
# never merely because a provider they might use is down.

INACTIVE_APPLICATION_STATUSES = {"COMPLETED", "REJECTED", "CANCELLED"}
_PENDING_JOB_STATUSES = {"QUEUED", "RUNNING", "RETRYING"}
BLOCKED_STATES = {"RETRY_PENDING", "ACTION_REQUIRED", "AWAITING_PROVIDER"}
_STATE_LABELS = {
    "RETRY_PENDING": "Waiting for retry", "ACTION_REQUIRED": "Needs citizen action (manual upload)",
    "AWAITING_PROVIDER": "Blocked: no available provider", "FALLBACK_SUCCEEDED": "Served by a fallback provider",
    "RECOVERED": "Recovered after the outage",
}


def _in_window(moment, start, end) -> bool:
    return moment is not None and (start is None or moment >= start) and (end is None or moment <= end)


def _operation_hit(operation: dict, provider_keys: set) -> bool:
    """The incident's provider was tried (or skipped as unavailable) and did
    not succeed in this operation."""
    return any((attempt.get("providerId") in provider_keys or attempt.get("provider") in provider_keys) and not attempt.get("success")
               for attempt in operation.get("attempts") or [])


def _requirement_impact_state(requirement: dict, provider_keys: set, window: tuple, open_now: bool,
                              editable: bool, has_alternative: bool) -> Optional[dict]:
    status = requirement.get("status")
    satisfied = status in SUCCESS_STATUSES
    hits = [op for op in requirement.get("providerHistory") or []
            if _in_window(_parse_ts(op.get("at")), *window) and _operation_hit(op, provider_keys)]
    if hits:
        last = hits[-1]
        if last.get("outcome") in SUCCESS_STATUSES:
            final = next((a for a in reversed(last.get("attempts") or []) if a.get("success")), {})
            return {"state": "FALLBACK_SUCCEEDED", "resolvedBy": final.get("provider") or final.get("providerId")}
        if satisfied:
            if _is_manual(requirement):
                resolved_by = "Citizen upload"
            elif requirement.get("providerId") in provider_keys:
                resolved_by = "Same provider after recovery"
            else:
                resolved_by = "Alternate provider"
            return {"state": "RECOVERED", "resolvedBy": resolved_by}
        return {"state": "RETRY_PENDING" if status == "WAITING" else "ACTION_REQUIRED", "resolvedBy": None}
    if open_now and editable and not satisfied and not has_alternative:
        return {"state": "AWAITING_PROVIDER", "resolvedBy": None}
    return None


def _incident_provider(session, provider_system: str) -> tuple:
    from sqlalchemy import or_
    from app.core.persistence import ProviderCapabilityRow
    provider = session.query(ProviderRow).filter(or_(ProviderRow.provider_id == provider_system, ProviderRow.name == provider_system)).first()
    keys = {provider_system}
    codes = set()
    if provider:
        keys |= {provider.provider_id, provider.name}
        codes = {row.capability_code for row in session.query(ProviderCapabilityRow).filter(
            ProviderCapabilityRow.provider_id == provider.provider_id, ProviderCapabilityRow.enabled.is_(True))}
    return keys, codes


def incident_impacts(incident_ids: Optional[list] = None, include_applications: bool = False) -> dict:
    """Impact for each incident (all, or ``incident_ids``), keyed by incident id."""
    with Session(engine) as session:
        query = session.query(ProviderIncidentRow)
        if incident_ids is not None:
            query = query.filter(ProviderIncidentRow.incident_id.in_(incident_ids))
        incidents = query.all()
        if not incidents:
            return {}
        applications = [(row.app_id, row.citizen_id, row.status, dict(row.payload or {})) for row in session.query(ApplicationRow).all()]
        schemes = {row.scheme_id: row.name for row in session.query(SchemeCatalogRow).all()}
        jobs = session.query(ProviderJobRow).all()
        providers = {incident.incident_id: _incident_provider(session, incident.provider_system) for incident in incidents}
        incidents = [(incident.incident_id, incident.status, incident.detected_at, incident.resolved_at) for incident in incidents]

    healthy_by_code = defaultdict(set)
    if any(status == "OPEN" for _, status, _, _ in incidents):
        from app.engine.adapters import integration_health
        from app.engine.registry import dependency_registry
        for entry in dependency_registry(integration_health()):
            if entry.get("healthStatus") in {"AVAILABLE", "HEALTHY"}:
                healthy_by_code[entry["requirementCode"]] |= {entry.get("providerId"), entry.get("provider")}

    by_app = {app_id: (citizen_id, app_status, payload) for app_id, citizen_id, app_status, payload in applications}
    result = {}
    for incident_id, incident_status, detected_at, resolved_at in incidents:
        provider_keys, codes = providers[incident_id]
        window = (_parse_ts(detected_at), _parse_ts(resolved_at))
        open_now = incident_status == "OPEN"
        affected = {}

        def _application_entry(app_id, citizen_id, app_status, payload):
            return {"appId": app_id, "citizenId": citizen_id, "schemeId": payload.get("serviceId"),
                    "schemeName": payload.get("schemeName") or schemes.get(payload.get("serviceId")) or payload.get("serviceId"),
                    "applicationStatus": app_status, "requirements": [], "jobs": []}

        for app_id, citizen_id, app_status, payload in applications:
            editable = app_status not in INACTIVE_APPLICATION_STATUSES and app_status != "SUBMITTED"
            for requirement in payload.get("requirements") or []:
                code = requirement.get("code")
                if code not in codes:
                    continue
                has_alternative = bool(healthy_by_code.get(code, set()) - provider_keys - {None})
                impact = _requirement_impact_state(requirement, provider_keys, window, open_now, editable, has_alternative)
                if impact:
                    entry = affected.setdefault(app_id, _application_entry(app_id, citizen_id, app_status, payload))
                    entry["requirements"].append({"requirementCode": code, "label": requirement.get("label") or code,
                                                  "requirementStatus": requirement.get("status"),
                                                  "stateLabel": _STATE_LABELS[impact["state"]], **impact})

        # Asynchronous provider jobs dispatched to this provider during the
        # incident window (the legacy dependency pipeline).
        incident_jobs = [job for job in jobs if job.provider_id in provider_keys and _in_window(_parse_ts(job.created_at), *window)]
        for job in incident_jobs:
            if not job.application_id:
                continue
            citizen_id, app_status, payload = by_app.get(job.application_id, (None, None, {}))
            entry = affected.setdefault(job.application_id, _application_entry(job.application_id, citizen_id, app_status, payload))
            entry["jobs"].append({"jobId": job.job_id, "status": job.status, "attempt": job.attempt, "maxAttempts": job.max_attempts})

        requirement_rows = [row for app in affected.values() for row in app["requirements"]]
        for app in affected.values():
            blocked = [row for row in app["requirements"] if row["state"] in BLOCKED_STATES]
            dead = [job for job in app["jobs"] if job["status"] == "DEAD_LETTER"]
            app["blocked"] = bool(blocked or dead)
            app["recovered"] = not app["blocked"] and any(row["state"] == "RECOVERED" for row in app["requirements"])
            if blocked:
                app["blockedStage"] = f"Requirement verification: {blocked[0]['label']} ({blocked[0]['stateLabel'].lower()})"
            elif dead:
                app["blockedStage"] = "Provider job moved to dead-letter"
            else:
                app["blockedStage"] = None
        summary = {
            "affectedCitizens": len({app["citizenId"] for app in affected.values() if app["citizenId"]}),
            "affectedApplicationsTotal": len(affected),
            "affectedSchemes": sorted({app["schemeName"] for app in affected.values() if app["schemeName"]}),
            "blockedOperations": sum(row["state"] in BLOCKED_STATES for row in requirement_rows)
                                 + sum(job.status == "DEAD_LETTER" for job in incident_jobs),
            "pendingRetries": sum(row["state"] == "RETRY_PENDING" for row in requirement_rows)
                              + sum(job.status in _PENDING_JOB_STATUSES for job in incident_jobs),
            "successfulFallbacks": sum(row["state"] == "FALLBACK_SUCCEEDED" for row in requirement_rows),
            "recoveredApplications": sum(app["recovered"] for app in affected.values()),
            "blockedApplications": sum(app["blocked"] for app in affected.values()),
        }
        if include_applications:
            summary["applications"] = sorted(affected.values(), key=lambda app: (not app["blocked"], app["appId"]))
        result[incident_id] = summary
    return result


# ---------------------------------------------------------------------------
# Department health (one entry per government department)
# ---------------------------------------------------------------------------
# A department is healthy or not independently of every other department and
# of the SANGAM platform itself: Revenue being unreachable never makes
# Education, Welfare, Health or Transport -- or SANGAM -- "degraded".

_HEALTHY = {"AVAILABLE", "HEALTHY"}


def _department_status(statuses: list[str]) -> str:
    if not statuses:
        return "NOT_CONFIGURED"
    if all(status in _HEALTHY for status in statuses):
        return "AVAILABLE"
    if all(status == "UNAVAILABLE" for status in statuses):
        return "UNAVAILABLE"
    return "DEGRADED"


def department_health_summary() -> dict:
    from app.engine.adapters import integration_health
    from app.engine.departments import DEPARTMENTS, department_label, provider_department
    from app.engine.registry import dependency_registry

    health = integration_health()
    registry = dependency_registry(health)
    health_by_name = {item["system"]: item for item in health}
    with Session(engine) as session:
        providers = [(row.provider_id, row.name) for row in session.query(ProviderRow).filter(ProviderRow.active.is_(True)).all()]
        open_incidents = [(row.incident_id, row.provider_system, row.detected_at) for row in
                          session.query(ProviderIncidentRow).filter(ProviderIncidentRow.status == "OPEN").all()]
        payloads = [(row.citizen_id, dict(row.payload or {})) for row in session.query(ApplicationRow).all()]

    by_department: dict[str, dict] = {}
    for provider_id, name in providers:
        key = provider_department(provider_id)
        if not key:
            continue
        entry = by_department.setdefault(key, {"providers": [], "providerIds": set(), "names": set()})
        item = health_by_name.get(name, {})
        capabilities = [cap for cap in registry if cap.get("providerId") == provider_id]
        entry["providerIds"].add(provider_id)
        entry["names"].add(name)
        entry["providers"].append({
            "providerId": provider_id, "name": name, "status": item.get("status", "UNKNOWN"),
            "simulated": bool(item.get("simulated")), "lastSuccessAt": item.get("lastSuccessAt"),
            "latencyMs": item.get("lastResponseMs"), "errorCategory": item.get("errorCategory"),
            "requirements": [{"requirementCode": cap["requirementCode"], "priority": cap.get("priority", 100)} for cap in capabilities],
        })

    # Primary vs fallback per requirement, across departments.
    ranked: dict[str, list] = defaultdict(list)
    for cap in registry:
        ranked[cap["requirementCode"]].append((cap.get("priority", 100), cap.get("provider") or "", cap.get("providerId")))
    primary_for = {code: sorted(items)[0][2] for code, items in ranked.items() if items}

    # Fallback usage from the persisted per-operation provider history.
    fallback_served: Counter = Counter()
    fallback_triggered: Counter = Counter()
    for _, payload in payloads:
        for requirement in payload.get("requirements") or []:
            for operation in requirement.get("providerHistory") or []:
                attempts = operation.get("attempts") or []
                winner = next((a for a in attempts if a.get("success")), None)
                if not winner or len(attempts) < 2:
                    continue
                served = provider_department(winner.get("providerId"))
                if served:
                    fallback_served[served] += 1
                for attempt in attempts:
                    if attempt is winner or attempt.get("success"):
                        continue
                    failed = provider_department(attempt.get("providerId"))
                    if failed and failed != served:
                        fallback_triggered[failed] += 1

    impacts = incident_impacts([incident_id for incident_id, _, _ in open_incidents], include_applications=True) if open_incidents else {}
    departments = []
    order = list(DEPARTMENTS)
    for key in sorted(by_department, key=lambda item: (not DEPARTMENTS.get(item, ("", "", False))[2], order.index(item) if item in order else 99)):
        entry = by_department[key]
        statuses = [provider["status"] for provider in entry["providers"]]
        incidents = [(incident_id, detected) for incident_id, system, detected in open_incidents if system in entry["names"]]
        affected_apps, affected_citizens = set(), set()
        for incident_id, _ in incidents:
            for application in (impacts.get(incident_id) or {}).get("applications") or []:
                affected_apps.add(application["appId"])
                if application.get("citizenId"):
                    affected_citizens.add(application["citizenId"])
        for provider in entry["providers"]:
            for requirement in provider["requirements"]:
                requirement["role"] = "PRIMARY" if primary_for.get(requirement["requirementCode"]) == provider["providerId"] else "FALLBACK"
        successes = [provider["lastSuccessAt"] for provider in entry["providers"] if provider["lastSuccessAt"]]
        latencies = [provider["latencyMs"] for provider in entry["providers"] if isinstance(provider["latencyMs"], (int, float))]
        departments.append({
            "key": key, "name": department_label(key), "nameMr": department_label(key, "mr"),
            "headline": DEPARTMENTS.get(key, ("", "", False))[2],
            "status": _department_status(statuses),
            "simulatedOutage": any(provider["simulated"] for provider in entry["providers"]),
            "latencyMs": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "lastSuccessfulVerification": max(successes) if successes else None,
            "supportedRequirements": sorted({req["requirementCode"] for provider in entry["providers"] for req in provider["requirements"]}),
            "providers": entry["providers"],
            "activeIncidents": len(incidents),
            "incidentSince": min((detected for _, detected in incidents), default=None),
            "fallbackUsage": {"servedAsFallback": fallback_served.get(key, 0), "fallbacksTriggered": fallback_triggered.get(key, 0)},
            "affectedApplications": len(affected_apps),
            "affectedCitizens": len(affected_citizens),
        })
    unhealthy = [department["name"] for department in departments if department["status"] != "AVAILABLE"]
    return {"platform": {"name": "SANGAM", "status": "HEALTHY"}, "departments": departments, "departmentsNotHealthy": unhealthy}


# ---------------------------------------------------------------------------
# Interoperability activity: what SANGAM did behind each Auto-Fill, for the
# Admin console. Read from the authoritative application rows (the trace is
# written in the same transaction as the requirement outcome). Traces are
# sanitized when written -- department, requirement, outcome and timing only.
# ---------------------------------------------------------------------------

def interoperability_activity(limit: int = 30, application_id: Optional[str] = None) -> dict:
    with Session(engine) as session:
        query = session.query(ApplicationRow)
        if application_id:
            query = query.filter(ApplicationRow.app_id == application_id)
        traces = []
        for row in query.all():
            for requirement in (row.payload or {}).get("requirements", []):
                trace = requirement.get("trace")
                if isinstance(trace, dict) and trace.get("steps"):
                    traces.append({**trace, "applicationStatus": row.status})
    traces.sort(key=lambda item: item.get("completedAt") or "", reverse=True)
    counts = Counter(item.get("outcome") for item in traces)
    return {"exchanges": traces[: max(1, min(int(limit), 200))], "total": len(traces),
            "summary": {"autoFilled": counts.get("AUTO_FILLED", 0), "viaFallback": counts.get("AUTO_FILLED_VIA_FALLBACK", 0),
                        "pending": counts.get("PENDING", 0), "noRecord": counts.get("NO_RECORD", 0),
                        "notAttached": counts.get("NOT_ATTACHED", 0) + counts.get("NOT_COMPLETED", 0)}}


def provider_exchange_stats(provider_id: str, provider_name: Optional[str] = None) -> dict:
    """Per-provider figures from real exchanges: last successful verification,
    recent failures, fallback use, and the applications / citizens affected."""
    keys = {key for key in (provider_id, provider_name) if key}
    last_success, failures, served_as_fallback = None, [], 0
    affected_apps, affected_citizens = set(), set()
    with Session(engine) as session:
        rows = [(row.app_id, row.citizen_id, dict(row.payload or {})) for row in session.query(ApplicationRow).all()]
    for app_id, citizen_id, payload in rows:
        for requirement in payload.get("requirements", []):
            for operation in requirement.get("providerHistory") or []:
                for attempt in operation.get("attempts") or []:
                    if attempt.get("providerId") not in keys and attempt.get("provider") not in keys:
                        continue
                    if attempt.get("success"):
                        if not last_success or (operation.get("at") or "") > last_success:
                            last_success = operation.get("at")
                    elif not attempt.get("recordNotFound"):
                        failures.append({"at": operation.get("at"), "applicationId": app_id, "requirementCode": requirement.get("code"),
                                         "errorCategory": attempt.get("errorCategory"), "skipped": bool(attempt.get("skipped"))})
                        affected_apps.add(app_id)
                        affected_citizens.add(citizen_id)
            provenance = requirement.get("provenance") or {}
            if provenance.get("providerId") in keys and provenance.get("fallbackUsed"):
                served_as_fallback += 1
    failures.sort(key=lambda item: item.get("at") or "", reverse=True)
    return {"lastSuccessfulVerification": last_success, "recentFailures": failures[:10], "failureCount": len(failures),
            "servedAsFallback": served_as_fallback, "affectedApplications": len(affected_apps), "affectedCitizens": len(affected_citizens)}
