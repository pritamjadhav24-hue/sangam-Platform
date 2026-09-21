from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id, render_synthetic_document
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import AcademicRecord, ScholarshipEligibility, Student, SyntheticDocument

SEED = 102
SCHOOL_CODES = [f"27{rng:04d}" for rng in (1001, 1042, 2087, 3120, 4055, 5099)]


def already_seeded(session) -> bool:
    return session.query(Student).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"students": 0, "academic_records": 0, "scholarship_eligibility": 0, "documents": 0}
    students = citizens_with_persona(citizens, "STUDENT")
    sequence = 1
    for citizen in students:
        student_id = record_id("EDU", sequence, "STU")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        age = 2026 - int(citizen["dob"][:4])
        standard = "UG-1" if age >= 18 else f"Std-{min(max(age - 5, 1), 10)}"
        session.add(Student(
            student_id=student_id, citizen_ref=citizen["citizenId"], student_name=name,
            date_of_birth=citizen["dob"], guardian_mobile=citizen["phone"],
            udise_school_code=rng.choice(SCHOOL_CODES), standard=standard,
        ))
        counts["students"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "VERIFIED", "PENDING": "AWAITING_SCHOOL_CONFIRMATION", "FAILURE": "DISCREPANCY_FLAGGED"}[bucket]
            percentage = round(rng.uniform(45, 98), 2) if status == "VERIFIED" else None
            record_ref = record_id("EDU", counts["academic_records"] + 1, "ACA")
            session.add(AcademicRecord(
                record_id=record_ref, student_id=student_id, academic_year="2025-2026",
                percentage=percentage, result="PASS" if status == "VERIFIED" else "PENDING", status=status,
            ))
            counts["academic_records"] += 1
            if status == "VERIFIED":
                session.add(SyntheticDocument(
                    document_id=f"{record_ref}-DOC", owner_reference=student_id, title="Academic Record",
                    issued_on="2026-04-30",
                    content_text=render_synthetic_document("Academic Record", name, "Education Department", {
                        "Academic Year": "2025-2026", "Percentage": percentage, "Result": "PASS",
                    }),
                ))
                counts["documents"] += 1

        if "BPL_HOUSEHOLD" in citizen.get("personas", []) or rng.random() < 0.4:
            bucket = case_bucket(rng, {"POSITIVE": 0.6, "PENDING": 0.25, "FAILURE": 0.15})
            eligible = bucket == "POSITIVE"
            session.add(ScholarshipEligibility(
                eligibility_id=record_id("EDU", counts["scholarship_eligibility"] + 1, "SCH"),
                student_id=student_id, scheme_reference="SCH-MH-2026",
                eligible=eligible, status="ASSESSED" if bucket != "PENDING" else "PENDING_ASSESSMENT",
            ))
            counts["scholarship_eligibility"] += 1
    return counts
