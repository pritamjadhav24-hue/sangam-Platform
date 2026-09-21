from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import CropLoan, Farmer, LandHolding, SchemeRegistration

SEED = 104
TALUKAS = ["Baramati", "Karad", "Niphad", "Akola", "Yavatmal", "Jalna"]
CROPS = ["Sugarcane", "Cotton", "Soybean", "Jowar", "Onion", "Grapes"]
BANKS = ["Maharashtra State Co-operative Bank", "Bank of Maharashtra", "NABARD-linked District Central Co-op Bank"]


def already_seeded(session) -> bool:
    return session.query(Farmer).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"farmers": 0, "land_holdings": 0, "crop_loans": 0, "scheme_registrations": 0}
    farmers = citizens_with_persona(citizens, "FARMER")
    sequence = 1
    for citizen in farmers:
        farmer_id = record_id("AGR", sequence, "FRM")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        session.add(Farmer(
            farmer_id=farmer_id, citizen_ref=citizen["citizenId"], farmer_name=name,
            dob=citizen["dob"], mobile=citizen["phone"], taluka=rng.choice(TALUKAS),
        ))
        counts["farmers"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "RECORDED", "PENDING": "SURVEY_PENDING", "FAILURE": "DISPUTED"}[bucket]
            session.add(LandHolding(
                holding_id=record_id("AGR", counts["land_holdings"] + 1, "HLD"),
                farmer_id=farmer_id, survey_number=f"{rng.randint(1, 500)}/{rng.randint(1, 9)}",
                crop_type=rng.choice(CROPS), irrigation_type=rng.choice(["Rainfed", "Canal", "Borewell"]),
                area_acres=round(rng.uniform(0.5, 8.0), 2), status=status,
            ))
            counts["land_holdings"] += 1

        bucket = case_bucket(rng, {"POSITIVE": 0.35, "PENDING": 0.2, "MISSING": 0.3, "FAILURE": 0.15})
        if bucket != "MISSING":
            status = {"POSITIVE": "ACTIVE", "PENDING": "SANCTIONED_AWAITING_DISBURSAL", "FAILURE": "DEFAULTED"}[bucket]
            session.add(CropLoan(
                loan_id=record_id("AGR", counts["crop_loans"] + 1, "LOAN"),
                farmer_id=farmer_id, loan_amount=round(rng.uniform(20000, 300000), 2), bank_name=rng.choice(BANKS), status=status,
            ))
            counts["crop_loans"] += 1

        bucket = case_bucket(rng, {"POSITIVE": 0.5, "PENDING": 0.3, "FAILURE": 0.2})
        session.add(SchemeRegistration(
            registration_id=record_id("AGR", counts["scheme_registrations"] + 1, "SCH"),
            farmer_id=farmer_id, scheme_name="Namo Shetkari Mahasanman Nidhi (demo)",
            status={"POSITIVE": "REGISTERED", "PENDING": "VERIFICATION_PENDING", "FAILURE": "REJECTED"}[bucket],
        ))
        counts["scheme_registrations"] += 1
    return counts
