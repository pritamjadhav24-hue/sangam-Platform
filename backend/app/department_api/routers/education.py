"""Education Sandbox API -- student academic records, enrolment and
scholarship eligibility assessment lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.education import models

router = APIRouter(prefix="/departments/education", tags=["education"])
SOURCE_SYSTEM = "Education Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


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


@router.get("/academic-records/{citizen_ref}")
def get_academic_record(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Latest VERIFIED marks record (a record awaiting school confirmation or
    flagged for discrepancy is not one SANGAM may rely on)."""
    student = session.query(models.Student).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if student:
        record = (session.query(models.AcademicRecord).filter_by(student_id=student.student_id, status="VERIFIED")
                  .order_by(models.AcademicRecord.created_at.desc()).first())
    if not student or not record or record.percentage is None:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "student_name": student.student_name, "date_of_birth": student.date_of_birth, "guardian_mobile": student.guardian_mobile,
        "marks_percentage": record.percentage, "result": record.result, "academic_year": record.academic_year,
        "udise_school_code": student.udise_school_code, "standard": student.standard,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.record_id, status=record.status)


@router.get("/enrollments/{citizen_ref}")
def get_enrollment(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Current enrolment (student record) verification."""
    student = session.query(models.Student).filter_by(citizen_ref=citizen_ref).first()
    if not student:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "student_name": student.student_name, "date_of_birth": student.date_of_birth, "guardian_mobile": student.guardian_mobile,
        "udise_school_code": student.udise_school_code, "standard": student.standard, "enrolled": True,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=student.student_id, status="ENROLLED")


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.Student, id_field="student_id", name_field="student_name", dob_field="date_of_birth",
                                                   phone_field="guardian_mobile", identifier_names=('student_id',)),
                  SOURCE_SYSTEM, {"academic-records": get_academic_record, "enrollments": get_enrollment, "scholarship-eligibility": get_scholarship_eligibility})
