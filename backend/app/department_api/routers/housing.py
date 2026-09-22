"""Housing Sandbox API -- public housing allotment status lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.housing import models

router = APIRouter(prefix="/departments/housing", tags=["housing"])
SOURCE_SYSTEM = "Housing Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/allotments/{citizen_ref}")
def get_allotment(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    applicant = session.query(models.Applicant).filter_by(citizen_ref=citizen_ref).first()
    application = None
    if applicant:
        application = (session.query(models.HousingApplication).filter_by(applicant_id=applicant.applicant_id)
                       .order_by(models.HousingApplication.created_at.desc()).first())
    if not applicant or not application:
        return not_found(SOURCE_SYSTEM, correlation_id)
    allotment = (session.query(models.Allotment).filter_by(application_id=application.application_id)
                .order_by(models.Allotment.created_at.desc()).first())
    data = {
        "applicant_name": applicant.applicant_name, "income_category": applicant.income_category,
        "scheme_name": application.scheme_name,
        "project_name": allotment.project_name if allotment else None,
        "unit_number": allotment.unit_number if allotment else None,
    }
    status = allotment.status if allotment else application.status
    record_id = allotment.allotment_id if allotment else application.application_id
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=record_id, status=status)
