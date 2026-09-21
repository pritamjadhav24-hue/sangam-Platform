from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import spelling_variant

from .models import Allotment, Applicant, HousingApplication

SEED = 108
PROJECTS = ["Ghar Kul Nagari Phase 2", "Sunrise Awas Yojana Blocks", "Shanti Nagar Housing Cluster"]


def already_seeded(session) -> bool:
    return session.query(Applicant).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"applicants": 0, "housing_applications": 0, "allotments": 0}
    adults = [citizen for citizen in citizens if 2026 - int(citizen["dob"][:4]) >= 21]
    relevant = [citizen for citizen in adults if rng.random() < 0.3]
    sequence = 1
    for citizen in relevant:
        applicant_id = record_id("HSG", sequence, "APP")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        income_category = "EWS" if "BPL_HOUSEHOLD" in citizen.get("personas", []) else rng.choice(["LIG", "MIG"])
        session.add(Applicant(
            applicant_id=applicant_id, citizen_ref=citizen["citizenId"], applicant_name=name,
            dob=citizen["dob"], mobile=citizen["phone"], income_category=income_category,
        ))
        counts["applicants"] += 1

        bucket = case_bucket(rng)
        if bucket == "MISSING":
            continue
        status = {"POSITIVE": "APPROVED", "PENDING": "UNDER_SCRUTINY", "FAILURE": "REJECTED"}[bucket]
        application_id = record_id("HSG", counts["housing_applications"] + 1, "AP")
        session.add(HousingApplication(
            application_id=application_id, applicant_id=applicant_id,
            scheme_name=rng.choice(PROJECTS), application_date="2025-11-01", status=status,
        ))
        counts["housing_applications"] += 1

        if status == "APPROVED":
            bucket = case_bucket(rng, {"POSITIVE": 0.5, "PENDING": 0.5})
            allotment_status = "ALLOTTED" if bucket == "POSITIVE" else "WAITLISTED"
            session.add(Allotment(
                allotment_id=record_id("HSG", counts["allotments"] + 1, "ALT"),
                application_id=application_id, project_name=rng.choice(PROJECTS),
                unit_number=f"B-{rng.randint(1, 12)}-{rng.randint(101, 412)}" if allotment_status == "ALLOTTED" else None,
                allotment_date="2026-02-15" if allotment_status == "ALLOTTED" else None, status=allotment_status,
            ))
            counts["allotments"] += 1
    return counts
