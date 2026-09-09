from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.engine.adapters import integration_health, set_integration_availability

router = APIRouter(prefix="/api/admin", tags=["Administration"])
@router.get("/audit-trail")
def audit_trail(): return {"zeroDocumentCentralization": True, "chainValid": audit_bus.verify(), "entries": audit_bus.entries, "events": event_bus.events}


class IntegrationAvailability(BaseModel):
    system: str
    available: bool
    error: Optional[str] = None


@router.get("/integration-health")
def integration_health_status():
    return {"integrations": integration_health(record_event=True)}


@router.post("/integration-health/simulate")
def simulate_integration_availability(body: IntegrationAvailability):
    try:
        return set_integration_availability(body.system, body.available, body.error)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))
