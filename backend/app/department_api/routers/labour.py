"""Labour Sandbox API -- registered worker and welfare board membership lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency
from app.sandbox.labour import models

router = APIRouter(prefix="/departments/labour", tags=["labour"])
SOURCE_SYSTEM = "Labour Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return {"status": "AVAILABLE", "sourceSystem": SOURCE_SYSTEM, "synthetic": True}


@router.get("/workers/{citizen_ref}")
def get_worker_registration(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    worker = session.query(models.RegisteredWorker).filter_by(citizen_ref=citizen_ref).first()
    establishment = None
    if worker:
        establishment = (session.query(models.EstablishmentRegistration).filter_by(worker_id=worker.worker_id)
                         .order_by(models.EstablishmentRegistration.created_at.desc()).first())
    if not worker or not establishment:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {
        "worker_name": worker.worker_name, "dateOfBirth": worker.dateOfBirth, "occupation": worker.occupation,
        "establishment_name": establishment.establishment_name, "registration_number": establishment.registration_number,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=establishment.establishment_id, status=establishment.status)


@router.get("/welfare-board-memberships/{citizen_ref}")
def get_welfare_board_membership(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    worker = session.query(models.RegisteredWorker).filter_by(citizen_ref=citizen_ref).first()
    membership = None
    if worker:
        membership = (session.query(models.WelfareBoardMembership).filter_by(worker_id=worker.worker_id)
                      .order_by(models.WelfareBoardMembership.created_at.desc()).first())
    if not worker or not membership:
        return not_found(SOURCE_SYSTEM, correlation_id)
    data = {"worker_name": worker.worker_name, "board_name": membership.board_name, "membership_number": membership.membership_number}
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=membership.membership_id, status=membership.status)
