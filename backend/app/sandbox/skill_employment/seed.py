from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import EmploymentRegistration, Jobseeker, SkillCertification

SEED = 109
TRADES = ["Electrician", "Welder", "Data Entry Operator", "Beautician", "Fitter", "Tailoring"]
CERT_BODIES = ["Maharashtra State Skill Development Society", "ITI Board Maharashtra"]
QUALIFICATIONS = ["10th Pass", "12th Pass", "ITI Diploma", "Graduate"]


def already_seeded(session) -> bool:
    return session.query(Jobseeker).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"jobseekers": 0, "skill_certifications": 0, "employment_registrations": 0}
    jobseekers = citizens_with_persona(citizens, "JOBSEEKER")
    sequence = 1
    for citizen in jobseekers:
        jobseeker_id = record_id("SKE", sequence, "JS")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        session.add(Jobseeker(
            jobseeker_id=jobseeker_id, citizen_ref=citizen["citizenId"], name=name,
            dateOfBirth=citizen["dob"], mobile=citizen["phone"], qualification=rng.choice(QUALIFICATIONS),
        ))
        counts["jobseekers"] += 1

        bucket = case_bucket(rng, {"POSITIVE": 0.45, "PENDING": 0.2, "MISSING": 0.2, "FAILURE": 0.15})
        if bucket != "MISSING":
            status = {"POSITIVE": "CERTIFIED", "PENDING": "ASSESSMENT_SCHEDULED", "FAILURE": "NOT_QUALIFIED"}[bucket]
            session.add(SkillCertification(
                certification_id=record_id("SKE", counts["skill_certifications"] + 1, "CRT"),
                jobseeker_id=jobseeker_id, trade=rng.choice(TRADES), certification_body=rng.choice(CERT_BODIES),
                issued_on="2025-08-20" if status == "CERTIFIED" else None, status=status,
            ))
            counts["skill_certifications"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "ACTIVE", "PENDING": "PROFILE_UNDER_REVIEW", "FAILURE": "DEREGISTERED"}[bucket]
            session.add(EmploymentRegistration(
                registration_id=record_id("SKE", counts["employment_registrations"] + 1, "EMP"),
                jobseeker_id=jobseeker_id, exchange_office=f"{citizen['district']} Employment Exchange",
                registration_date="2026-01-10" if status == "ACTIVE" else None, status=status,
            ))
            counts["employment_registrations"] += 1
    return counts
