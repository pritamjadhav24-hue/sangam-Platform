"""Labour Sandbox API -- registered worker and welfare board membership lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.labour import models

router = APIRouter(prefix="/departments/labour", tags=["labour"])
SOURCE_SYSTEM = "Labour Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


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


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.RegisteredWorker, id_field="worker_id", name_field="worker_name", dob_field="dateOfBirth",
                                                   phone_field="mobile", identifier_names=('worker_id',)),
                  SOURCE_SYSTEM, {"workers": get_worker_registration, "welfare-board-memberships": get_welfare_board_membership})
