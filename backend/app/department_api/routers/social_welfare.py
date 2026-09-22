"""Social Welfare Sandbox API -- welfare scheme enrollment status lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.social_welfare import models

router = APIRouter(prefix="/departments/social-welfare", tags=["social_welfare"])
SOURCE_SYSTEM = "Social Welfare Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/scheme-enrollments/{citizen_ref}")
def get_scheme_enrollment(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    beneficiary = session.query(models.Beneficiary).filter_by(citizen_ref=citizen_ref).first()
    enrollment = None
    if beneficiary:
        enrollment = (session.query(models.SchemeEnrollment).filter_by(beneficiary_id=beneficiary.beneficiary_id)
                      .order_by(models.SchemeEnrollment.created_at.desc()).first())
    if not beneficiary or not enrollment:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "name": beneficiary.name, "date_of_birth": beneficiary.date_of_birth,
        "social_category": beneficiary.social_category, "scheme_name": enrollment.scheme_name,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=enrollment.enrollment_id, status=enrollment.status)
