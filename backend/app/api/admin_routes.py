from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from app.core.admin_insights import (
    analytics_report, classify_application_outcome, effective_access_model, scheme_catalogue, scheme_detail,
)
from app.core.audit_bus import audit_bus
from app.core.auth import JWT_EXPIRES_SECONDS, _bearer, decode_token, require_roles
from app.core.event_bus import event_bus
from app.engine.adapters import integration_health, set_integration_availability
from app.engine.registry import dependency_registry
from app.core.demo_state import reset_demo_state
from app.mocks.education_dept import set_income_conflict
from app.core.persistence import (
    job_operational_summary, recent_provider_jobs, provider_job_detail,
    provider_operational_summary, replay_dead_letter_job, worker_operational_status,
    _safe_job_view, ApplicationRow, DependencyRow, ProviderJobRow, EntityReviewRow,
    ConflictReviewRow, AuditEntryRow, engine, provider_incidents_summary,
    open_provider_incident_count, provider_registry_snapshot, provider_registry_detail,
    reset_demo_database,
)
from app.core.redis_service import RedisService, RedisUnavailable
from app.core.rate_limit import enforce
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/admin", tags=["Administration"])
@router.get("/audit-trail")
def audit_trail(user: dict = Depends(require_roles("ADMIN"))):
    # audit_bus.entries is append-only and hash-chained in sequence order --
    # that underlying order/integrity is never touched here, this only
    # reverses the *response* so the newest activity reads first.
    return {"zeroDocumentCentralization": True, "chainValid": audit_bus.verify(), "entries": list(reversed(audit_bus.entries)), "events": event_bus.events}


class IntegrationAvailability(BaseModel):
    system: str
    available: bool
    error: Optional[str] = None


class ConflictSimulation(BaseModel):
    enabled: bool


@router.get("/integration-health")
def integration_health_status(user: dict = Depends(require_roles("ADMIN"))):
    return {"integrations": integration_health(record_event=True)}


@router.get("/dependency-registry")
def dependency_registry_status(user: dict = Depends(require_roles("ADMIN"))):
    return {"services": dependency_registry(integration_health(record_event=True))}


@router.post("/integration-health/simulate")
def simulate_integration_availability(body: IntegrationAvailability, user: dict = Depends(require_roles("ADMIN"))):
    try:
        result = set_integration_availability(body.system, body.available, body.error)
        audit_bus.append(user["userId"], "INTEGRATION_HEALTH", "Administrator changed simulated integration availability", body.system, "SIMULATE", payload={"system": body.system, "status": result["status"], "actorRole": user["role"]})
        return result
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/conflict-simulation")
def simulate_conflict(body: ConflictSimulation, user: dict = Depends(require_roles("ADMIN"))):
    value = set_income_conflict(body.enabled)
    audit_bus.append(user["userId"], "CONFLICT_SIMULATION", "Administrator changed deterministic conflict scenario", "Education Department", "SIMULATE", payload={"enabled": body.enabled, "actorRole": user["role"]})
    return {"enabled": body.enabled, "educationFamilyAnnualIncome": value}


@router.post("/demo/reset")
def reset_demo(user: dict = Depends(require_roles("ADMIN"))):
    if os.getenv("SANGAM_ENV", "development").strip().lower() in {"production", "prod"}:
        raise HTTPException(status_code=403, detail="Demo reset is disabled in production.")
    removed = reset_demo_database()
    reset_demo_state()
    return {"success": True, "message": "Demo activity cleared; seeded reference data retained.", "sessionReset": True, "removed": removed}


@router.get("/operations/providers")
def provider_operations(user: dict = Depends(require_roles("ADMIN"))):
    return {"providers": provider_operational_summary()}


@router.get("/operations/providers/registry")
def provider_registry(user: dict = Depends(require_roles("ADMIN"))):
    return {"providers": provider_registry_snapshot()}


@router.get("/analytics")
def admin_analytics(
    start: Optional[str] = Query(None, description="YYYY-MM-DD, inclusive"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD, inclusive"),
    status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    requirement: Optional[str] = Query(None),
    incident_status: Optional[str] = Query(None, alias="incidentStatus"),
    user: dict = Depends(require_roles("ADMIN")),
):
    try:
        return analytics_report(start=start, end=end, status=status, outcome=outcome, provider=provider,
                                requirement=requirement, incident_status=incident_status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/schemes")
def admin_schemes(user: dict = Depends(require_roles("ADMIN"))):
    return {"schemes": scheme_catalogue()}


@router.get("/schemes/{scheme_id}")
def admin_scheme_detail(scheme_id: str, user: dict = Depends(require_roles("ADMIN"))):
    detail = scheme_detail(scheme_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    return detail


@router.get("/profile")
def admin_profile(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
                  user: dict = Depends(require_roles("ADMIN"))):
    claims = decode_token(credentials.credentials)
    as_iso = lambda seconds: datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    return {
        "user": {"userId": user.get("userId"), "name": user.get("name"), "role": user.get("role")},
        "session": {
            "issuedAt": as_iso(claims["iat"]),
            "expiresAt": as_iso(claims["exp"]),
            "lifetimeSeconds": JWT_EXPIRES_SECONDS,
            "sessionRef": f"{claims['jti'][:6]}…",
        },
        "access": effective_access_model(request.app.routes),
    }


@router.get("/operations/providers/registry/{provider_id}")
def provider_registry_detail_route(provider_id: str, user: dict = Depends(require_roles("ADMIN"))):
    detail = provider_registry_detail(provider_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    return detail


@router.get("/operations/worker")
def worker_operations(user: dict = Depends(require_roles("ADMIN"))):
    try:
        return {"workers": worker_operational_status()}
    except Exception as error:
        raise HTTPException(status_code=503, detail="Worker operational state is unavailable.") from error


@router.get("/operations/jobs/summary")
def job_summary(user: dict = Depends(require_roles("ADMIN"))):
    return job_operational_summary()


@router.get("/operations/jobs/dead-letter")
def dead_letter_jobs(limit: int = Query(50, ge=1, le=100), user: dict = Depends(require_roles("ADMIN"))):
    return {"jobs": recent_provider_jobs(limit, dead_letter_only=True)}


@router.get("/operations/jobs/recent")
def recent_jobs(limit: int = Query(50, ge=1, le=100), user: dict = Depends(require_roles("ADMIN"))):
    return {"jobs": recent_provider_jobs(limit)}


@router.get("/operations/jobs/{job_id}")
def job_detail(job_id: str, user: dict = Depends(require_roles("ADMIN"))):
    job = provider_job_detail(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/operations/jobs/{job_id}/replay")
def replay_job(job_id: str, user: dict = Depends(require_roles("ADMIN"))):
    enforce("admin_replay", user["userId"], limit=20, window_seconds=60)
    try:
        return replay_dead_letter_job(job_id, RedisService())
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (RedisUnavailable, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Provider job replay is unavailable.") from error


@router.get("/operations/incidents")
def operations_incidents(user: dict = Depends(require_roles("ADMIN"))):
    return {"incidents": provider_incidents_summary()}


@router.get("/operations/overview")
def operations_overview(user: dict = Depends(require_roles("ADMIN"))):
    with Session(engine) as session:
        apps = session.query(ApplicationRow).all()
        app_list = [dict(a.payload or {}) for a in apps]

        status_counts: dict[str, int] = {}
        # Mutually exclusive, requirement-derived outcome buckets -- shared
        # with Analytics via classify_application_outcome so the two views
        # can never disagree.
        outcome_counts = Counter()
        for a in app_list:
            st = a.get("status", "DRAFT")
            status_counts[st] = status_counts.get(st, 0) + 1
            outcome_counts[classify_application_outcome(a)] += 1
        auto_verified = outcome_counts["automaticallyVerified"]
        manually_fulfilled = outcome_counts["manuallyFulfilled"]
        citizen_action_required = outcome_counts["citizenActionRequired"]
        officer_review_required = outcome_counts["officerReviewRequired"]
        retry_in_progress = outcome_counts["retryInProgress"]

        providers = provider_operational_summary()
        jobs = job_operational_summary()

        dead_letter_count = jobs.get("counts", {}).get("DEAD_LETTER", 0)
        entity_reviews_count = sum(1 for r in session.query(EntityReviewRow).all() if (r.payload or {}).get("status") == "WAITING_FOR_OFFICER")
        conflict_reviews_count = sum(1 for r in session.query(ConflictReviewRow).all() if (r.payload or {}).get("status") == "WAITING_FOR_OFFICER")
        active_incidents = open_provider_incident_count()

        workers = []
        try:
            workers = worker_operational_status()
        except Exception:
            pass

        ledger_valid = audit_bus.verify()
        provider_health_statuses = [p.get("health", {}).get("status") for p in providers]
        healthy_count = sum(1 for s in provider_health_statuses if s in {"AVAILABLE", "HEALTHY"})
        down_count = sum(1 for s in provider_health_statuses if s == "UNAVAILABLE")
        degraded_count = sum(1 for s in provider_health_statuses if s not in {"AVAILABLE", "HEALTHY", "UNAVAILABLE"})
        # An honest, data-driven summary label rather than a flat
        # "Operational" that would contradict a failed ledger check or an
        # open provider incident right next to it.
        if not ledger_valid:
            system_state = "DEGRADED_LEDGER_INTEGRITY"
        elif active_incidents > 0 or down_count > 0:
            system_state = "DEGRADED_PROVIDER_INCIDENT"
        else:
            system_state = "OPERATIONAL"

        return {
            "system": {
                "state": system_state,
                "postgresConnected": True,
                "redis": RedisService().health_check().get("status", "UNAVAILABLE") if RedisService().enabled else "LOCAL_MEMORY",
                "workersActive": sum(1 for w in workers if w.get("status") in {"AVAILABLE", "BUSY"}),
                "auditChainValid": ledger_valid,
                "auditEntriesCount": len(audit_bus.entries),
                "architecture": "FEDERATED",
            },
            "applications": {
                "total": len(app_list),
                "byStatus": status_counts,
                "automaticallyVerified": auto_verified,
                "manuallyFulfilled": manually_fulfilled,
                "citizenActionRequired": citizen_action_required,
                "officerReviewRequired": officer_review_required,
                "retryInProgress": retry_in_progress,
                # Kept for backward compatibility with existing callers;
                # equals citizenActionRequired + officerReviewRequired.
                "requiringAttention": citizen_action_required + officer_review_required,
            },
            "providers": {
                "registered": len(providers),
                "healthy": healthy_count,
                "down": down_count,
                "degraded": degraded_count,
            },
            "jobs": jobs,
            "exceptions": {
                "deadLetterJobs": dead_letter_count,
                "entityReviews": entity_reviews_count,
                "conflictReviews": conflict_reviews_count,
                # Provider incidents are a distinct, system-level concept
                # from dead-letter jobs/reviews -- intentionally NOT folded
                # into totalAlerts below.
                "activeProviderIncidents": active_incidents,
                "totalAlerts": dead_letter_count + entity_reviews_count + conflict_reviews_count,
            },
        }


@router.get("/applications")
def list_admin_applications(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_roles("ADMIN")),
):
    with Session(engine) as session:
        query = session.query(ApplicationRow)
        if status and status.upper() != "ALL":
            query = query.filter(ApplicationRow.status == status.upper())
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(or_(ApplicationRow.app_id.ilike(s), ApplicationRow.citizen_id.ilike(s)))
        
        rows = query.order_by(ApplicationRow.created_at.desc().nullslast()).limit(limit).all()
        
        results = []
        for r in rows:
            payload = dict(r.payload or {})
            reqs = payload.get("requirements", [])
            fulfilled = sum(1 for req in reqs if req.get("status") in {"VALIDATED", "RETRIEVED", "USER_OVERRIDDEN"})
            has_exception = any(req.get("status") in {"ACTION_REQUIRED", "FAILED", "REJECTED"} for req in reqs) or r.status in {"WAITING_FOR_OFFICER", "CONFLICT_DETECTED", "VERIFICATION_FAILED"}
            
            results.append({
                "appId": r.app_id,
                "citizenId": r.citizen_id,
                "status": r.status,
                "serviceId": payload.get("serviceId"),
                "schemeName": payload.get("schemeName") or payload.get("serviceId", "Unknown Scheme"),
                "createdAt": payload.get("createdAt") or (r.created_at.isoformat() if r.created_at else None),
                "updatedAt": payload.get("updatedAt") or (r.updated_at.isoformat() if r.updated_at else None),
                "requirementsCount": len(reqs),
                "fulfilledCount": fulfilled,
                "hasException": has_exception,
            })
        return {"applications": results}


def _requirement_lineage_steps(req: dict, fulfillment_method: str, is_fallback: bool,
                                primary_candidate: dict | None, chosen_provider: str | None,
                                candidate_count: int) -> list[dict]:
    """A requirement's orchestration story as an ordered list of steps, built
    only from fields already persisted on the requirement (status, attempts,
    providerId, documentId, errorCategory) -- no separate lineage-event log
    exists yet, so this is derived on read rather than fabricated.
    """
    steps = [{"step": "Requirement identified", "detail": req.get("label") or req.get("code")}]
    status = req.get("status")
    attempts = req.get("attempts", 0) or 0
    success_statuses = {"VALIDATED", "RETRIEVED", "USER_OVERRIDDEN", "FOUND"}

    if fulfillment_method == "MANUAL_UPLOAD":
        steps.append({"step": "Citizen manual upload", "detail": "Document uploaded directly by citizen"})
        if status in success_statuses:
            steps.append({"step": "Validation passed", "detail": "Requirement fulfilled"})
        return steps

    if fulfillment_method == "PENDING":
        steps.append({"step": "Awaiting action", "detail": "No retrieval attempted yet"})
        return steps

    # AUTO_FILL
    steps.append({"step": "Consent recorded", "detail": "Citizen granted Auto-Fill consent"})
    fallback_attempts = req.get("fallbackAttempts")
    if fallback_attempts:
        # Ground truth from the real in-request fallback cascade: one
        # PRIMARY/FALLBACK selection + outcome step per provider actually
        # tried in this operation, in order -- e.g. "Provider A (PRIMARY)
        # -> FAILED -> Provider B (FALLBACK) -> SUCCESS".
        steps.append({"step": "Provider discovery evaluated", "detail": f"{candidate_count} eligible provider(s) considered"})
        for attempt in fallback_attempts:
            role = "FALLBACK" if attempt.get("isFallback") else "PRIMARY"
            if attempt.get("skipped"):
                steps.append({"step": f"{attempt.get('provider')} ({role})", "detail": f"Skipped: provider {str(attempt.get('healthStatus') or 'unavailable').lower()}"})
                continue
            steps.append({"step": f"{attempt.get('provider')} ({role})", "detail": "Attempt started"})
            if attempt.get("success"):
                steps.append({"step": "Retrieval succeeded", "detail": attempt.get("provider")})
            else:
                steps.append({"step": "Attempt failed", "detail": attempt.get("errorCategory") or "Unknown error"})
    else:
        if primary_candidate:
            steps.append({"step": "Provider discovery evaluated", "detail": f"{candidate_count} eligible provider(s) considered"})
            steps.append({
                "step": "Primary provider unavailable" if is_fallback else "Primary provider selected",
                "detail": primary_candidate.get("provider"),
            })
        if is_fallback:
            steps.append({"step": "Fallback evaluation", "detail": "Next eligible, healthy provider identified"})
            steps.append({"step": "Fallback provider selected", "detail": chosen_provider})
    if attempts > 1:
        steps.append({"step": "Automated retry", "detail": f"{attempts - 1} retr{'y' if attempts - 1 == 1 else 'ies'} attempted"})

    if status in success_statuses:
        steps.append({"step": "Document/data retrieved", "detail": chosen_provider or "Provider"})
        steps.append({"step": "Validation passed", "detail": "Requirement fulfilled"})
    elif status == "ACTION_REQUIRED":
        steps.append({"step": "Retries exhausted", "detail": f"{attempts} attempt(s) made"})
        steps.append({"step": "Automatic retrieval stopped", "detail": req.get("errorCategory") or "Automated retrieval unavailable"})
        steps.append({"step": "Citizen notified", "detail": "Manual upload option presented"})
    elif status == "FAILED":
        steps.append({"step": "Retrieval failed", "detail": req.get("errorCategory") or "Non-retryable error"})
    elif status == "WAITING":
        steps.append({"step": "Automated retry in progress", "detail": f"Attempt {attempts} of {req.get('maxAttempts', 3)}"})
    elif status == "REJECTED":
        steps.append({"step": "Validation failed", "detail": "Retrieved data did not pass validation"})
    return steps


@router.get("/applications/{application_id}")
def get_admin_application_detail(
    application_id: str,
    user: dict = Depends(require_roles("ADMIN")),
):
    with Session(engine) as session:
        row = session.get(ApplicationRow, application_id)
        if not row:
            raise HTTPException(status_code=404, detail="Application not found.")
        payload = dict(row.payload or {})
        
        dep_rows = session.query(DependencyRow).filter(DependencyRow.app_id == application_id).all()
        dependencies = [dict(d.payload or {}, dependencyId=d.dependency_id, status=d.status, jobId=d.job_id, jobStatus=d.job_status, attempts=d.attempts) for d in dep_rows]
        
        job_rows = session.query(ProviderJobRow).filter(
            or_(ProviderJobRow.application_id == application_id, ProviderJobRow.correlation_id == application_id)
        ).order_by(ProviderJobRow.created_at.desc()).all()
        jobs = [_safe_job_view(j) for j in job_rows]
        
        entity_revs = [r.payload for r in session.query(EntityReviewRow).filter(EntityReviewRow.app_id == application_id).all()]
        conflict_revs = [r.payload for r in session.query(ConflictReviewRow).filter(ConflictReviewRow.app_id == application_id).all()]
        
        audit_entries = [e.payload for e in session.query(AuditEntryRow).filter(AuditEntryRow.correlation_id == application_id).order_by(AuditEntryRow.sequence.asc()).all()]
        
        health_list = integration_health()
        registry_list = dependency_registry(health_list)
        open_incidents_by_provider = {i["providerSystem"]: i for i in provider_incidents_summary() if i["status"] == "OPEN"}

        requirements_detail = []
        for req in payload.get("requirements", []):
            code = req.get("code")
            candidates = [c for c in registry_list if c.get("requirementCode") == code]
            candidates_sorted = sorted(candidates, key=lambda c: (c.get("priority", 100), c.get("provider", "")))

            chosen_provider = req.get("providerId")
            fulfillment_method = "MANUAL_UPLOAD" if req.get("documentId") or req.get("fulfillmentMethod") == "MANUAL_UPLOAD" else ("AUTO_FILL" if chosen_provider or req.get("canonical") else "PENDING")

            primary_candidate = candidates_sorted[0] if candidates_sorted else None
            fallback_attempts = req.get("fallbackAttempts")
            if fallback_attempts:
                # Ground truth recorded by the real in-request fallback
                # cascade (app.engine.requirement_fulfillment) -- exactly
                # which providers were tried, in order, for this attempt.
                # Preferred over inference below, which can drift once a
                # primary provider recovers after the fact.
                is_fallback = bool(req.get("isFallback"))
                primary_attempt_provider = fallback_attempts[0].get("provider")
            else:
                is_fallback = bool(primary_candidate) and fulfillment_method == "AUTO_FILL" and primary_candidate.get("providerId") != chosen_provider and primary_candidate.get("provider") != chosen_provider
                primary_attempt_provider = primary_candidate.get("provider") if primary_candidate else None
            primary_incident = open_incidents_by_provider.get(primary_candidate.get("providerId")) if primary_candidate else None

            decision_reason = None
            if fulfillment_method == "AUTO_FILL":
                if fallback_attempts:
                    if not is_fallback:
                        decision_reason = f"Primary provider ({primary_attempt_provider}) succeeded on the first attempt."
                    else:
                        failed_providers = ", ".join(a.get("provider") for a in fallback_attempts[:-1])
                        successful_provider = fallback_attempts[-1].get("provider")
                        how = "was unavailable" if all(a.get("skipped") for a in fallback_attempts[:-1]) else "failed"
                        decision_reason = f"Primary provider ({failed_providers}) {how}; fallback source ({successful_provider}) was evaluated and succeeded within the same operation -- no repeat citizen action required."
                elif candidates_sorted:
                    top = candidates_sorted[0]
                    if not is_fallback:
                        decision_reason = f"Primary authoritative source ({top.get('provider')}) selected based on healthy status ({top.get('healthStatus')}) and priority tier {top.get('priority', 10)}."
                    else:
                        decision_reason = f"Primary provider ({top.get('provider')}) was unavailable; fallback source ({chosen_provider}) selected because it is the next eligible, healthy provider for this requirement."
                else:
                    decision_reason = f"Provider ({chosen_provider}) selected from capability catalog."
            elif fulfillment_method == "MANUAL_UPLOAD":
                decision_reason = "Citizen provided document via direct manual upload."

            related_entity_rev = next((er for er in entity_revs if er.get("requirementCode") == code), None)
            related_conflict_rev = next((cr for cr in conflict_revs if cr.get("requirementCode") == code), None)

            requirements_detail.append({
                **req,
                "fulfillmentMethod": fulfillment_method,
                "chosenProvider": chosen_provider,
                "primaryProvider": primary_candidate.get("provider") if primary_candidate else None,
                "isFallback": is_fallback,
                "primaryProviderIncident": primary_incident,
                "lineageSteps": _requirement_lineage_steps(req, fulfillment_method, is_fallback, primary_candidate, chosen_provider, len(candidates_sorted)),
                "sourceCandidates": [
                    {
                        "provider": c.get("provider"),
                        "providerId": c.get("providerId"),
                        "priority": c.get("priority", 100),
                        "healthStatus": c.get("healthStatus"),
                        "service": c.get("service"),
                        "isChosen": c.get("providerId") == chosen_provider or c.get("provider") == chosen_provider,
                    }
                    for c in candidates_sorted
                ],
                "decisionReason": decision_reason,
                "entityReview": related_entity_rev,
                "conflictReview": related_conflict_rev,
            })
        
        return {
            "appId": row.app_id,
            "citizenId": row.citizen_id,
            "status": row.status,
            "serviceId": payload.get("serviceId"),
            "schemeName": payload.get("schemeName") or payload.get("serviceId"),
            "createdAt": payload.get("createdAt") or (row.created_at.isoformat() if row.created_at else None),
            "updatedAt": payload.get("updatedAt") or (row.updated_at.isoformat() if row.updated_at else None),
            "statusHistory": payload.get("statusHistory", []),
            "requirements": requirements_detail,
            "dependencies": dependencies,
            "jobs": jobs,
            "entityReviews": entity_revs,
            "conflictReviews": conflict_revs,
            "auditEntries": audit_entries,
        }
