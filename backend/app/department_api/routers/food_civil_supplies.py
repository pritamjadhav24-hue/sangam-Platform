"""Food & Civil Supplies Sandbox API -- ration card lookups."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.department_api.common import correlation_id_header, envelope, not_found, session_dependency, department_health
from app.department_api.resolution import PersonIndex, register_resolver
from app.sandbox.food_civil_supplies import models

router = APIRouter(prefix="/departments/food-civil-supplies", tags=["food_civil_supplies"])
SOURCE_SYSTEM = "Food & Civil Supplies Sandbox (SYNTHETIC/DEMO)"
get_session = session_dependency(models.ENGINE)


@router.get("/health")
def health():
    return department_health(models.ENGINE, SOURCE_SYSTEM)


@router.get("/ration-cards/{citizen_ref}")
def get_ration_card(citizen_ref: str, correlation_id=Depends(correlation_id_header), session=Depends(get_session)):
    card = session.query(models.RationCard).filter_by(citizen_ref=citizen_ref).first()
    if not card:
        return not_found(SOURCE_SYSTEM, correlation_id)
    member_count = session.query(models.HouseholdMember).filter_by(card_id=card.card_id).count()
    data = {
        "head_of_household_name": card.head_of_household_name, "dob": card.dob,
        "card_number": card.card_number, "card_category": card.card_category,
        "household_member_count": member_count,
    }
    return envelope(data, source_system=SOURCE_SYSTEM, correlation_id=correlation_id, record_id=card.card_id, status=card.status)


# Canonical record lookup for SANGAM: this department finds the person in its
# own records (see app.department_api.resolution) and serves the record
# through the handlers above.
register_resolver(router, get_session, PersonIndex(models.RationCard, id_field="card_id", name_field="head_of_household_name", dob_field="dob",
                                                   phone_field="mobile", identifier_names=('card_id',)),
                  SOURCE_SYSTEM, {"ration-cards": get_ration_card})
