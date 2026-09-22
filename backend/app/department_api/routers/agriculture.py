"""Agriculture Sandbox API -- farmer registration and crop-loan lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.agriculture import models

router = APIRouter(prefix="/departments/agriculture", tags=["agriculture"])
SOURCE_SYSTEM = "Agriculture Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/farmers/{citizen_ref}")
def get_farmer_registration(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    farmer = session.query(models.Farmer).filter_by(citizen_ref=citizen_ref).first()
    if not farmer:
        return not_found(SOURCE_SYSTEM, correlation_id)
    registration = (session.query(models.SchemeRegistration).filter_by(farmer_id=farmer.farmer_id)
                    .order_by(models.SchemeRegistration.created_at.desc()).first())
    holding = (session.query(models.LandHolding).filter_by(farmer_id=farmer.farmer_id)
               .order_by(models.LandHolding.created_at.desc()).first())
    data = {
        "farmer_name": farmer.farmer_name, "dob": farmer.dob, "taluka": farmer.taluka,
        "crop_type": holding.crop_type if holding else None,
        "area_acres": holding.area_acres if holding else None,
        "scheme_name": registration.scheme_name if registration else None,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=farmer.farmer_id, status=registration.status if registration else "NOT_REGISTERED_FOR_SCHEME")


@router.get("/crop-loans/{citizen_ref}")
def get_crop_loan(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    farmer = session.query(models.Farmer).filter_by(citizen_ref=citizen_ref).first()
    loan = None
    if farmer:
        loan = (session.query(models.CropLoan).filter_by(farmer_id=farmer.farmer_id)
               .order_by(models.CropLoan.created_at.desc()).first())
    if not farmer or not loan:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"farmer_name": farmer.farmer_name, "loan_amount": loan.loan_amount, "bank_name": loan.bank_name}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=loan.loan_id, status=loan.status)
