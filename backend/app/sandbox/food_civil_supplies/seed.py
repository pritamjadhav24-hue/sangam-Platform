from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import spelling_variant

from .models import EntitlementRecord, HouseholdMember, RationCard

SEED = 107
COMMODITIES = ["Rice", "Wheat", "Sugar", "Kerosene"]
RELATIONS = ["Spouse", "Child", "Parent", "Sibling"]


def already_seeded(session) -> bool:
    return session.query(RationCard).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"ration_cards": 0, "household_members": 0, "entitlement_records": 0}
    # Every BPL_HOUSEHOLD persona plus a general slice of the pool holds a ration card.
    from app.seeds.synthetic_identity_pool import citizens_with_persona
    bpl = citizens_with_persona(citizens, "BPL_HOUSEHOLD")
    others = [citizen for citizen in citizens if citizen not in bpl and rng.random() < 0.3]
    sequence = 1
    for citizen in bpl + others:
        card_id = record_id("FCS", sequence, "CARD")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        category = "AAY" if "BPL_HOUSEHOLD" in citizen.get("personas", []) and rng.random() < 0.3 else ("BPL" if "BPL_HOUSEHOLD" in citizen.get("personas", []) else "APL")
        bucket = case_bucket(rng, {"POSITIVE": 0.65, "PENDING": 0.2, "FAILURE": 0.15})
        status = {"POSITIVE": "ACTIVE", "PENDING": "VERIFICATION_PENDING", "FAILURE": "SUSPENDED"}[bucket]
        session.add(RationCard(
            card_id=card_id, citizen_ref=citizen["citizenId"], head_of_household_name=name,
            dob=citizen["dob"], mobile=citizen["phone"],
            card_number=f"RC-{rng.randint(1000000, 9999999)}" if status == "ACTIVE" else None,
            card_category=category, status=status,
        ))
        counts["ration_cards"] += 1

        member_count = rng.randint(0, 3)
        for _ in range(member_count):
            session.add(HouseholdMember(
                member_id=record_id("FCS", counts["household_members"] + 1, "MEM"),
                card_id=card_id, member_name=f"{rng.choice(['Ravi', 'Sita', 'Om', 'Meera'])} {name.split(' ')[-1]}",
                relation=rng.choice(RELATIONS), dob=None,
            ))
            counts["household_members"] += 1

        if status == "ACTIVE":
            for commodity in rng.sample(COMMODITIES, k=rng.randint(1, len(COMMODITIES))):
                bucket = case_bucket(rng, {"POSITIVE": 0.7, "PENDING": 0.15, "FAILURE": 0.15})
                session.add(EntitlementRecord(
                    entitlement_id=record_id("FCS", counts["entitlement_records"] + 1, "ENT"),
                    card_id=card_id, month="2026-09", commodity=commodity,
                    quantity_kg=round(rng.uniform(1, 10), 1) if bucket == "POSITIVE" else None,
                    status={"POSITIVE": "DISBURSED", "PENDING": "SCHEDULED", "FAILURE": "STOCK_UNAVAILABLE"}[bucket],
                ))
                counts["entitlement_records"] += 1
    return counts
