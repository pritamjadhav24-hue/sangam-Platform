from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import BirthCertificate, ImmunizationRecord, ResidentIndex

SEED = 110
WARDS = ["Ward 3 - Kothrud", "Ward 7 - Andheri West", "Ward 2 - Sadar", "Ward 5 - Panchavati"]
HOSPITALS = ["Municipal General Hospital", "Civil Hospital Maternity Wing", "Primary Health Centre"]
VACCINES = ["BCG", "OPV", "DPT", "Measles"]


def already_seeded(session) -> bool:
    return session.query(ResidentIndex).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"residents": 0, "birth_certificates": 0, "immunization_records": 0}
    young = [citizen for citizen in citizens if 2026 - int(citizen["dob"][:4]) <= 12]
    new_parents_children = citizens_with_persona(citizens, "NEW_PARENT")
    relevant = young + [citizen for citizen in new_parents_children if citizen not in young]
    sequence = 1
    for citizen in relevant:
        resident_id = record_id("MUN", sequence, "RES")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        session.add(ResidentIndex(
            resident_id=resident_id, citizen_ref=citizen["citizenId"], name=name,
            dob=citizen["dob"], phone=citizen["phone"], ward=rng.choice(WARDS),
        ))
        counts["residents"] += 1

        if citizen in young:
            bucket = case_bucket(rng)
            if bucket != "MISSING":
                status = {"POSITIVE": "REGISTERED", "PENDING": "AWAITING_HOSPITAL_CONFIRMATION", "FAILURE": "RECORD_DISPUTE"}[bucket]
                session.add(BirthCertificate(
                    certificate_id=record_id("MUN", counts["birth_certificates"] + 1, "BC"),
                    resident_id=resident_id, registration_number=f"BC-{rng.randint(100000, 999999)}" if status == "REGISTERED" else None,
                    place_of_birth=rng.choice(HOSPITALS), status=status,
                ))
                counts["birth_certificates"] += 1

            for dose, vaccine in enumerate(rng.sample(VACCINES, k=rng.randint(1, len(VACCINES))), start=1):
                bucket = case_bucket(rng, {"POSITIVE": 0.6, "PENDING": 0.3, "FAILURE": 0.1})
                status = {"POSITIVE": "ADMINISTERED", "PENDING": "SCHEDULED", "FAILURE": "MISSED"}[bucket]
                session.add(ImmunizationRecord(
                    record_id=record_id("MUN", counts["immunization_records"] + 1, "IMM"),
                    resident_id=resident_id, vaccine=vaccine, dose_number=dose,
                    date_administered="2026-03-01" if status == "ADMINISTERED" else None, status=status,
                ))
                counts["immunization_records"] += 1
    return counts


def seed_demo(session, _citizens=None) -> dict:
    """Curated public-demo citizens (app.seeds.demo_citizens), idempotent."""
    from app.seeds.demo_citizens import demo_records
    added = 0
    for index, (citizen, spec) in enumerate(demo_records("municipal_health"), start=1):
        if session.query(ResidentIndex).filter_by(citizen_ref=citizen["citizenId"]).first():
            continue
        resident_id = f"MUN-DEMO-RES-{index:03d}"
        session.add(ResidentIndex(
            resident_id=resident_id, citizen_ref=citizen["citizenId"], name=spec.get("name", citizen["name"]),
            dob=spec.get("dob", citizen["dob"]), phone=spec.get("phone", citizen["phone"]), ward=citizen["district"],
        ))
        session.flush()
        if spec.get("birth"):
            session.add(BirthCertificate(
                certificate_id=f"MUN-DEMO-BC-{index:03d}", resident_id=resident_id, registration_number=f"BC-DEMO-{index:04d}",
                place_of_birth="Municipal General Hospital", status="REGISTERED",
            ))
        if spec.get("immunization"):
            session.add(ImmunizationRecord(
                record_id=f"MUN-DEMO-IMM-{index:03d}", resident_id=resident_id, vaccine="Tetanus booster", dose_number=1,
                date_administered="2025-01-12", status="ADMINISTERED",
            ))
        added += 1
    return {"demoCitizens": added}
