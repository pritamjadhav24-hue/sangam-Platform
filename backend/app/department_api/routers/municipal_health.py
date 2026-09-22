"""Municipal Health Sandbox API -- birth certificate and immunization record
lookups (civil registration + public health)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.municipal_health import models

router = APIRouter(prefix="/departments/municipal-health", tags=["municipal_health"])
SOURCE_SYSTEM = "Municipal Health Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/birth-certificates/{citizen_ref}")
def get_birth_certificate(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    certificate = None
    if resident:
        certificate = (session.query(models.BirthCertificate).filter_by(resident_id=resident.resident_id)
                       .order_by(models.BirthCertificate.created_at.desc()).first())
    if not resident or not certificate:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"name": resident.name, "dob": resident.dob, "place_of_birth": certificate.place_of_birth, "registration_number": certificate.registration_number}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=certificate.certificate_id, status=certificate.status)


@router.get("/immunization-records/{citizen_ref}")
def get_immunization_record(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    if not resident:
        return not_found(SOURCE_SYSTEM, correlation_id)
    doses = session.query(models.ImmunizationRecord).filter_by(resident_id=resident.resident_id).order_by(models.ImmunizationRecord.dose_number).all()
    if not doses:
        return not_found(SOURCE_SYSTEM, correlation_id)
    administered = [d for d in doses if d.status == "ADMINISTERED"]
    overall_status = "FULLY_IMMUNIZED" if len(administered) == len(doses) else ("PARTIALLY_IMMUNIZED" if administered else "NOT_IMMUNIZED")
    data = {
        "name": resident.name, "dob": resident.dob,
        "doses": [{"vaccine": d.vaccine, "dose_number": d.dose_number, "status": d.status} for d in doses],
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=f"{resident.resident_id}-IMM", status=overall_status)
