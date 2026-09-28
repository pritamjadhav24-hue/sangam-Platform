"""Skill Development & Employment Sandbox API -- skill certification and
employment exchange registration lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.skill_employment import models

router = APIRouter(prefix="/departments/skill-employment", tags=["skill_employment"])
SOURCE_SYSTEM = "Skill Development & Employment Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


@router.get("/skill-certifications/{citizen_ref}")
def get_skill_certification(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    jobseeker = session.query(models.Jobseeker).filter_by(citizen_ref=citizen_ref).first()
    certification = None
    if jobseeker:
        certification = (session.query(models.SkillCertification).filter_by(jobseeker_id=jobseeker.jobseeker_id)
                         .order_by(models.SkillCertification.created_at.desc()).first())
    if not jobseeker or not certification:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"name": jobseeker.name, "qualification": jobseeker.qualification, "trade": certification.trade, "certification_body": certification.certification_body}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=certification.certification_id, status=certification.status)


@router.get("/employment-registrations/{citizen_ref}")
def get_employment_registration(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    jobseeker = session.query(models.Jobseeker).filter_by(citizen_ref=citizen_ref).first()
    registration = None
    if jobseeker:
        registration = (session.query(models.EmploymentRegistration).filter_by(jobseeker_id=jobseeker.jobseeker_id)
                        .order_by(models.EmploymentRegistration.created_at.desc()).first())
    if not jobseeker or not registration:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"name": jobseeker.name, "exchange_office": registration.exchange_office}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=registration.registration_id, status=registration.status)


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.Jobseeker, id_field="jobseeker_id", name_field="name", dob_field="dateOfBirth",
                                                   phone_field="mobile", identifier_names=('jobseeker_id',)),
                  SOURCE_SYSTEM, {"skill-certifications": get_skill_certification, "employment-registrations": get_employment_registration})
