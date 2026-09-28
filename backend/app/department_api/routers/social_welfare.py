"""Social Welfare Sandbox API -- caste/category certificates, DBT bank
linkage, verified household income and welfare scheme enrolment."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.social_welfare import models

router = APIRouter(prefix="/departments/social-welfare", tags=["social_welfare"])
SOURCE_SYSTEM = "Social Welfare Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


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


def _beneficiary_identity(beneficiary) -> dict:
    return {"name": beneficiary.name, "date_of_birth": beneficiary.date_of_birth, "mobile": beneficiary.mobile, "address": beneficiary.address_line}


@router.get("/caste-certificates/{citizen_ref}")
def get_caste_certificate(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    beneficiary = session.query(models.Beneficiary).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if beneficiary:
        record = (session.query(models.CasteCertificate).filter_by(beneficiary_id=beneficiary.beneficiary_id, status="ISSUED")
                  .order_by(models.CasteCertificate.created_at.desc()).first())
    if not beneficiary or not record:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {**_beneficiary_identity(beneficiary), "caste_category": record.caste, "issued_on": record.issued_on}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.certificate_id, status=record.status)


@router.get("/bank-linkages/{citizen_ref}")
def get_bank_linkage(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Direct-benefit-transfer (DBT) bank account linkage."""
    beneficiary = session.query(models.Beneficiary).filter_by(citizen_ref=citizen_ref).first()
    record = None
    if beneficiary:
        record = (session.query(models.BankLinkage).filter_by(beneficiary_id=beneficiary.beneficiary_id)
                  .order_by(models.BankLinkage.created_at.desc()).first())
    if not beneficiary or not record or record.account_status != "LINKED":
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {**_beneficiary_identity(beneficiary), "bank_name": record.bank_name, "dbt_status": "VERIFIED"}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record.linkage_id, status=record.account_status)


@router.get("/beneficiary-income/{citizen_ref}")
def get_beneficiary_income(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    """Household income the department verified during beneficiary
    enrolment -- an authorised equivalent of an income certificate."""
    beneficiary = session.query(models.Beneficiary).filter_by(citizen_ref=citizen_ref).first()
    if not beneficiary or beneficiary.verified_annual_income is None:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {**_beneficiary_identity(beneficiary), "household_income": beneficiary.verified_annual_income,
            "income_verified_on": beneficiary.income_verified_on, "verification_basis": "Beneficiary enrolment income verification"}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=f"{beneficiary.beneficiary_id}-INC", status="VERIFIED")


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.Beneficiary, id_field="beneficiary_id", name_field="name", dob_field="date_of_birth",
                                                   phone_field="mobile", identifier_names=('beneficiary_id',)),
                  SOURCE_SYSTEM, {"caste-certificates": get_caste_certificate, "bank-linkages": get_bank_linkage, "beneficiary-income": get_beneficiary_income, "scheme-enrollments": get_scheme_enrollment})
