"""Education Sandbox API -- scholarship eligibility assessment lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.education import models

router = APIRouter(prefix="/departments/education", tags=["education"])
SOURCE_SYSTEM = "Education Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/scholarship-eligibility/{citizen_ref}")
def get_scholarship_eligibility(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    student = session.query(models.Student).filter_by(citizen_ref=citizen_ref).first()
    eligibility = None
    if student:
        eligibility = (session.query(models.ScholarshipEligibility).filter_by(student_id=student.student_id)
                       .order_by(models.ScholarshipEligibility.created_at.desc()).first())
    if not student or not eligibility:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "student_name": student.student_name, "date_of_birth": student.date_of_birth,
        "udise_school_code": student.udise_school_code, "standard": student.standard,
        "scheme_reference": eligibility.scheme_reference, "eligible": eligibility.eligible,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=eligibility.eligibility_id, status=eligibility.status)
