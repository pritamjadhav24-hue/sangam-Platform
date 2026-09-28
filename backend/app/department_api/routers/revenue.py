"""Revenue Sandbox API -- land records (7/12-style extract lookups) and
issued income certificates.

The in-process Revenue Department mock remains the primary (priority 10)
income provider for the scholarship flow; the income-certificate resource
here is registered as a lower-priority alternate provider for the same
INCOME_PROOF capability, so SANGAM's provider discovery can fall back to it
when the primary is unavailable. Both are synthetic sandbox systems.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.revenue import models

router = APIRouter(prefix="/departments/revenue", tags=["revenue"])
SOURCE_SYSTEM = "Revenue Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


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


@router.get("/income-certificates/{citizen_ref}")
def get_income_certificate(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Latest ISSUED income certificate only -- an application still under
    verification or rejected is not a certificate SANGAM may rely on."""
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if resident:
        record = (session.query(models.IncomeCertificate)
                  .filter_by(resident_id=resident.resident_id, status="ISSUED")
                  .order_by(models.IncomeCertificate.created_at.desc()).first())
    if not resident or not record or record.annual_income is None:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "annual_income": record.annual_income, "financial_year": record.financial_year,
        "resident_name": resident.full_name, "taluka": resident.taluka,
        "dob": resident.dob, "mobile": resident.mobile, "address": resident.address_line,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.certificate_id, status=record.status)


@router.get("/domicile-certificates/{citizen_ref}")
def get_domicile_certificate(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Latest ISSUED domicile (residence) certificate for the citizen."""
    resident = session.query(models.ResidentIndex).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if resident:
        record = (session.query(models.DomicileCertificate)
                  .filter_by(resident_id=resident.resident_id, status="ISSUED")
                  .order_by(models.DomicileCertificate.created_at.desc()).first())
    if not resident or not record:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "domicile_state": record.state, "issued_on": record.issued_on, "valid_until": record.valid_until,
        "resident_name": resident.full_name, "dob": resident.dob, "mobile": resident.mobile,
        "address": resident.address_line, "taluka": resident.taluka,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.certificate_id, status=record.status)


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.ResidentIndex, id_field="resident_id", name_field="full_name", dob_field="dob",
                                                   phone_field="mobile", identifier_names=('resident_id',)),
                  SOURCE_SYSTEM, {"income-certificates": get_income_certificate, "domicile-certificates": get_domicile_certificate, "land-records": get_land_record})
