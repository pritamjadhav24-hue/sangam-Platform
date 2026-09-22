"""Transport (RTO) Sandbox API -- vehicle registration and driving licence
lookups. This department demonstrates API_KEY auth (see
DEPARTMENT_API_KEY_TRANSPORT / PROVIDER_TRANSPORT-SANDBOX-API_API_KEY)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, require_api_key, session_dependency
from app.sandbox.transport import models

router = APIRouter(prefix="/departments/transport", tags=["transport"], dependencies=[Depends(require_api_key("TRANSPORT"))])
SOURCE_SYSTEM = "Transport Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/vehicle-registrations/{citizen_ref}")
def get_vehicle_registration(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    registration = None
    if resident:
        registration = (session.query(models.VehicleRegistration).filter_by(resident_id=resident.resident_id)
                        .order_by(models.VehicleRegistration.created_at.desc()).first())
    if not resident or not registration:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "name": resident.name, "dob": resident.dob, "vehicle_number": registration.vehicle_number,
        "vehicle_class": registration.vehicle_class, "registration_date": registration.registration_date,
        "rto_office": resident.rto_office,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=registration.registration_id, status=registration.status)


@router.get("/driving-licences/{citizen_ref}")
def get_driving_licence(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    licence = None
    if resident:
        licence = (session.query(models.DrivingLicence).filter_by(resident_id=resident.resident_id)
                  .order_by(models.DrivingLicence.created_at.desc()).first())
    if not resident or not licence:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"name": resident.name, "licence_class": licence.licence_class, "valid_until": licence.valid_until}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=licence.licence_id, status=licence.status)
