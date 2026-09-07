from fastapi import APIRouter
from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus

router = APIRouter(prefix="/api/admin", tags=["Administration"])
@router.get("/audit-trail")
def audit_trail(): return {"zeroDocumentCentralization": True, "chainValid": audit_bus.verify(), "entries": audit_bus.entries, "events": event_bus.events}
