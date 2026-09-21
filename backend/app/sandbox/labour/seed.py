from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import EstablishmentRegistration, RegisteredWorker, WelfareBoardMembership

SEED = 106
OCCUPATIONS = ["Construction Labourer", "Mason", "Painter", "Electrician (unorganized)", "Plumber", "Domestic Worker"]
ESTABLISHMENTS = ["Shivshakti Construction Co.", "Deccan Infra Builders", "Sahyadri Contractors", "Konkan Realty Works"]


def already_seeded(session) -> bool:
    return session.query(RegisteredWorker).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"workers": 0, "establishment_registrations": 0, "welfare_board_memberships": 0}
    workers = citizens_with_persona(citizens, "INDUSTRIAL_WORKER")
    sequence = 1
    for citizen in workers:
        worker_id = record_id("LAB", sequence, "WRK")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        session.add(RegisteredWorker(
            worker_id=worker_id, citizen_ref=citizen["citizenId"], worker_name=name,
            dateOfBirth=citizen["dob"], mobile=citizen["phone"], occupation=rng.choice(OCCUPATIONS),
        ))
        counts["workers"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "ACTIVE", "PENDING": "VERIFICATION_PENDING", "FAILURE": "TERMINATED"}[bucket]
            session.add(EstablishmentRegistration(
                establishment_id=record_id("LAB", counts["establishment_registrations"] + 1, "EST"),
                worker_id=worker_id, establishment_name=rng.choice(ESTABLISHMENTS),
                registration_number=f"EST-{rng.randint(10000, 99999)}" if status == "ACTIVE" else None, status=status,
            ))
            counts["establishment_registrations"] += 1

        bucket = case_bucket(rng, {"POSITIVE": 0.45, "PENDING": 0.25, "MISSING": 0.2, "FAILURE": 0.1})
        if bucket != "MISSING":
            status = {"POSITIVE": "ACTIVE_MEMBER", "PENDING": "APPLICATION_UNDER_REVIEW", "FAILURE": "LAPSED"}[bucket]
            session.add(WelfareBoardMembership(
                membership_id=record_id("LAB", counts["welfare_board_memberships"] + 1, "MEM"),
                worker_id=worker_id, membership_number=f"MBOCWWB-{rng.randint(100000, 999999)}" if status == "ACTIVE_MEMBER" else None, status=status,
            ))
            counts["welfare_board_memberships"] += 1
    return counts
