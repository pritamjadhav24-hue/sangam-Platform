from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import DrivingLicence, ResidentIndex, VehicleRegistration

SEED = 105
RTO_OFFICES = ["Pune RTO", "Mumbai Central RTO", "Nagpur RTO", "Nashik RTO", "Thane RTO"]
VEHICLE_CLASSES = ["Two Wheeler", "LMV - Car", "Auto Rickshaw", "Goods Carrier"]


def already_seeded(session) -> bool:
    return session.query(ResidentIndex).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"residents": 0, "vehicle_registrations": 0, "driving_licences": 0}
    eligible = [citizen for citizen in citizens if 2026 - int(citizen["dob"][:4]) >= 18]
    relevant = citizens_with_persona(eligible, "VEHICLE_OWNER") + [
        citizen for citizen in eligible if rng.random() < 0.25 and citizen not in citizens_with_persona(eligible, "VEHICLE_OWNER")
    ]
    sequence = 1
    for citizen in relevant:
        resident_id = record_id("TRN", sequence, "RES")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        session.add(ResidentIndex(
            resident_id=resident_id, citizen_ref=citizen["citizenId"], name=name,
            dob=citizen["dob"], phone=citizen["phone"], rto_office=rng.choice(RTO_OFFICES),
        ))
        counts["residents"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "ACTIVE", "PENDING": "RENEWAL_PENDING", "FAILURE": "SUSPENDED"}[bucket]
            session.add(VehicleRegistration(
                registration_id=record_id("TRN", counts["vehicle_registrations"] + 1, "VEH"),
                resident_id=resident_id, vehicle_number=f"MH-{rng.randint(1, 49):02d}-{rng.choice('ABCDEFGH')}{rng.choice('ABCDEFGH')}-{rng.randint(1000, 9999)}",
                vehicle_class=rng.choice(VEHICLE_CLASSES), registration_date="2024-11-15" if status == "ACTIVE" else None, status=status,
            ))
            counts["vehicle_registrations"] += 1

        bucket = case_bucket(rng, {"POSITIVE": 0.5, "PENDING": 0.25, "MISSING": 0.15, "FAILURE": 0.1})
        if bucket != "MISSING":
            status = {"POSITIVE": "VALID", "PENDING": "RENEWAL_APPLIED", "FAILURE": "EXPIRED"}[bucket]
            session.add(DrivingLicence(
                licence_id=record_id("TRN", counts["driving_licences"] + 1, "DL"),
                resident_id=resident_id, licence_number=f"MH{rng.randint(10, 49)}{rng.randint(20150000, 20260000)}" if status != "PENDING" else None,
                licence_class=rng.choice(["LMV", "MCWG", "LMV+MCWG"]), valid_until="2031-06-30" if status == "VALID" else None, status=status,
            ))
            counts["driving_licences"] += 1
    return counts


def seed_demo(session, _citizens=None) -> dict:
    """Curated public-demo citizens (app.seeds.demo_citizens), idempotent."""
    from app.seeds.demo_citizens import demo_records
    added = 0
    for index, (citizen, spec) in enumerate(demo_records("transport"), start=1):
        if session.query(ResidentIndex).filter_by(citizen_ref=citizen["citizenId"]).first():
            continue
        resident_id = f"TRN-DEMO-RES-{index:03d}"
        session.add(ResidentIndex(
            resident_id=resident_id, citizen_ref=citizen["citizenId"], name=spec.get("name", citizen["name"]),
            dob=spec.get("dob", citizen["dob"]), phone=spec.get("phone", citizen["phone"]), rto_office="Nashik RTO",
        ))
        session.flush()
        if spec.get("vehicle"):
            session.add(VehicleRegistration(
                registration_id=f"TRN-DEMO-VEH-{index:03d}", resident_id=resident_id, vehicle_number="MH-15-DK-4821",
                vehicle_class="Two Wheeler", registration_date="2023-02-14", status="ACTIVE",
            ))
        if spec.get("licence"):
            session.add(DrivingLicence(
                licence_id=f"TRN-DEMO-DL-{index:03d}", resident_id=resident_id, licence_number="MH1520190034512",
                licence_class="LMV+MCWG", valid_until="2039-09-02", status="VALID",
            ))
        added += 1
    return {"demoCitizens": added}
