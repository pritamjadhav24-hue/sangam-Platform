from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.audit_bus import audit_bus
from app.core.auth import require_roles
from app.core.event_bus import event_bus
from app.engine.adapters import integration_health, set_integration_availability
from app.engine.registry import dependency_registry
from app.core.demo_state import reset_demo_state
from app.mocks.education_dept import set_income_conflict

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
