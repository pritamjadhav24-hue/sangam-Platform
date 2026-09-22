"""Revenue Sandbox API -- land records (7/12-style extract lookups).

Domicile/income certificates stay served by the existing in-process Revenue
Department mock (unchanged); this REST surface adds the land-record resource
that only exists in the Phase 1 sandbox, demonstrating the new HTTP-backed
provider path without touching the existing scholarship flow.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.revenue import models

router = APIRouter(prefix="/departments/revenue", tags=["revenue"])
SOURCE_SYSTEM = "Revenue Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/land-records/{citizen_ref}")
def get_land_record(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if resident:
        record = (session.query(models.LandRecord).filter_by(resident_id=resident.resident_id)
                  .order_by(models.LandRecord.created_at.desc()).first())
    if not resident or not record:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "survey_number": record.survey_number, "khata_number": record.khata_number,
        "area_hectares": record.area_hectares, "land_type": record.land_type,
        "resident_name": resident.full_name, "taluka": resident.taluka, "village": resident.village,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.record_id, status=record.status)
