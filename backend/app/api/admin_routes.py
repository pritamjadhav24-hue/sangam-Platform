from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.core.audit_bus import audit_bus
from app.core.auth import require_roles
from app.core.event_bus import event_bus
from app.engine.adapters import integration_health, set_integration_availability
from app.engine.registry import dependency_registry
from app.core.demo_state import reset_demo_state
from app.mocks.education_dept import set_income_conflict
from app.core.persistence import (
    job_operational_summary, recent_provider_jobs, provider_job_detail,
    provider_operational_summary, replay_dead_letter_job, worker_operational_status,
    _safe_job_view, ApplicationRow, DependencyRow, ProviderJobRow, EntityReviewRow,
    ConflictReviewRow, AuditEntryRow, engine,
)
from app.core.redis_service import RedisService, RedisUnavailable
from app.core.rate_limit import enforce
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/admin", tags=["Administration"])
@router.get("/audit-trail")
def audit_trail(user: dict = Depends(require_roles("ADMIN"))): return {"zeroDocumentCentralization": True, "chainValid": audit_bus.verify(), "entries": audit_bus.entries, "events": event_bus.events}


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
    reset_demo_state()
    return {"success": True, "message": "In-memory demo state reset to deterministic defaults.", "sessionReset": True}


@router.get("/operations/providers")
def provider_operations(user: dict = Depends(require_roles("ADMIN"))):
    return {"providers": provider_operational_summary()}


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


@router.get("/operations/overview")
def operations_overview(user: dict = Depends(require_roles("ADMIN"))):
    with Session(engine) as session:
        apps = session.query(ApplicationRow).all()
        app_list = [dict(a.payload or {}) for a in apps]
        
        status_counts: dict[str, int] = {}
        auto_verified = 0
        exceptions = 0
        success_statuses = {"VALIDATED", "RETRIEVED", "USER_OVERRIDDEN"}
        for a in app_list:
            st = a.get("status", "DRAFT")
            status_counts[st] = status_counts.get(st, 0) + 1
            reqs = a.get("requirements", [])
            has_exc = any(r.get("status") in {"ACTION_REQUIRED", "FAILED", "REJECTED"} for r in reqs) or st in {"WAITING_FOR_OFFICER", "CONFLICT_DETECTED", "VERIFICATION_FAILED"}
            if has_exc:
                exceptions += 1
            else:
                # Automatic verification is a requirement-level fact, not an
                # application-status guess: every requirement must have
                # actually reached a success status, and none of them may
                # have been satisfied by a citizen's manual document upload
                # (documentId set, or fulfillmentMethod == MANUAL_UPLOAD) --
                # otherwise a manually-uploaded application would be
                # miscounted as automatically verified.
                fulfilled = [r for r in reqs if r.get("status") in success_statuses]
                is_manual = lambda r: bool(r.get("documentId")) or r.get("fulfillmentMethod") == "MANUAL_UPLOAD"
                if reqs and len(fulfilled) == len(reqs) and not any(is_manual(r) for r in fulfilled):
                    auto_verified += 1

        providers = provider_operational_summary()
        jobs = job_operational_summary()

        dead_letter_count = jobs.get("counts", {}).get("DEAD_LETTER", 0)
        entity_reviews_count = sum(1 for r in session.query(EntityReviewRow).all() if (r.payload or {}).get("status") == "WAITING_FOR_OFFICER")
        conflict_reviews_count = sum(1 for r in session.query(ConflictReviewRow).all() if (r.payload or {}).get("status") == "WAITING_FOR_OFFICER")
        
        workers = []
        try:
            workers = worker_operational_status()
        except Exception:
            pass

        return {
            "system": {
                "postgres": "CONNECTED",
                "redis": RedisService().health_check().get("status", "UNAVAILABLE") if RedisService().enabled else "LOCAL_MEMORY",
                "workersActive": sum(1 for w in workers if w.get("status") in {"AVAILABLE", "BUSY"}),
                "auditChainValid": audit_bus.verify(),
                "auditEntriesCount": len(audit_bus.entries),
                "zeroDocumentCentralization": True,
            },
            "applications": {
                "total": len(app_list),
                "byStatus": status_counts,
                "automaticallyVerified": auto_verified,
                "requiringAttention": exceptions,
            },
            "providers": {
                "total": len(providers),
                "available": sum(1 for p in providers if p.get("health", {}).get("status") in {"AVAILABLE", "HEALTHY"}),
                "degraded": sum(1 for p in providers if p.get("health", {}).get("status") not in {"AVAILABLE", "HEALTHY"}),
            },
            "jobs": jobs,
            "exceptions": {
                "deadLetterJobs": dead_letter_count,
                "entityReviews": entity_reviews_count,
                "conflictReviews": conflict_reviews_count,
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
        
        requirements_detail = []
        for req in payload.get("requirements", []):
            code = req.get("code")
            candidates = [c for c in registry_list if c.get("requirementCode") == code]
            candidates_sorted = sorted(candidates, key=lambda c: (c.get("priority", 100), c.get("provider", "")))
            
            chosen_provider = req.get("providerId")
            fulfillment_method = "MANUAL_UPLOAD" if req.get("documentId") or req.get("fulfillmentMethod") == "MANUAL_UPLOAD" else ("AUTO_FILL" if chosen_provider or req.get("canonical") else "PENDING")
            
            decision_reason = None
            if fulfillment_method == "AUTO_FILL":
                if candidates_sorted:
                    top = candidates_sorted[0]
                    if top.get("providerId") == chosen_provider:
                        decision_reason = f"Primary authoritative source ({top.get('provider')}) selected based on healthy status ({top.get('healthStatus')}) and priority tier {top.get('priority', 10)}."
                    else:
                        decision_reason = f"Fallback source ({chosen_provider}) selected because higher-priority provider was unavailable or non-responsive."
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
