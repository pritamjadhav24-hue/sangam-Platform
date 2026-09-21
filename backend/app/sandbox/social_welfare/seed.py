from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id, render_synthetic_document
from app.seeds.synthetic_identity_pool import spelling_variant

from .models import BankLinkage, Beneficiary, CasteCertificate, SchemeEnrollment, SyntheticDocument

SEED = 103
CASTE_CATEGORIES = ["OPEN", "OBC", "SC", "ST", "NT-B", "VJNT", "SBC"]
BANKS = ["Bank of Maharashtra", "State Bank of India", "Union Bank of India", "Central Bank of India"]


def already_seeded(session) -> bool:
    return session.query(Beneficiary).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"beneficiaries": 0, "caste_certificates": 0, "bank_linkages": 0, "scheme_enrollments": 0, "documents": 0}
    # Roughly two-thirds of the citizen pool has a Social Welfare Department touchpoint,
    # mirroring how caste/DBT records are broader than any single scheme's applicant pool.
    relevant = [citizen for citizen in citizens if rng.random() < 0.65]
    sequence = 1
    for citizen in relevant:
        beneficiary_id = record_id("SW", sequence, "BEN")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        category = rng.choice(CASTE_CATEGORIES)
        session.add(Beneficiary(
            beneficiary_id=beneficiary_id, citizen_ref=citizen["citizenId"], name=name,
            date_of_birth=citizen["dob"], mobile=citizen["phone"], social_category=category,
        ))
        counts["beneficiaries"] += 1

        if category != "OPEN":
            bucket = case_bucket(rng)
            if bucket != "MISSING":
                status = {"POSITIVE": "ISSUED", "PENDING": "UNDER_VERIFICATION", "FAILURE": "REJECTED"}[bucket]
                cert_id = record_id("SW", counts["caste_certificates"] + 1, "CST")
                session.add(CasteCertificate(
                    certificate_id=cert_id, beneficiary_id=beneficiary_id, caste=category,
                    issued_on="2025-05-01" if status == "ISSUED" else None, status=status,
                ))
                counts["caste_certificates"] += 1
                if status == "ISSUED":
                    session.add(SyntheticDocument(
                        document_id=f"{cert_id}-DOC", owner_reference=beneficiary_id, title="Caste Certificate",
                        issued_on="2025-05-01",
                        content_text=render_synthetic_document("Caste Certificate", name, "Social Welfare Department", {
                            "Certificate No": cert_id, "Category": category,
                        }),
                    ))
                    counts["documents"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "LINKED", "PENDING": "VERIFICATION_PENDING", "FAILURE": "LINK_FAILED"}[bucket]
            session.add(BankLinkage(
                linkage_id=record_id("SW", counts["bank_linkages"] + 1, "BNK"),
                beneficiary_id=beneficiary_id, bank_name=rng.choice(BANKS), account_status=status,
            ))
            counts["bank_linkages"] += 1

        if "BPL_HOUSEHOLD" in citizen.get("personas", []):
            bucket = case_bucket(rng, {"POSITIVE": 0.5, "PENDING": 0.3, "FAILURE": 0.2})
            session.add(SchemeEnrollment(
                enrollment_id=record_id("SW", counts["scheme_enrollments"] + 1, "ENR"),
                beneficiary_id=beneficiary_id, scheme_name="Sanjay Gandhi Niradhar Yojana (demo)",
                status={"POSITIVE": "ENROLLED", "PENDING": "APPLICATION_UNDER_REVIEW", "FAILURE": "DECLINED"}[bucket],
            ))
            counts["scheme_enrollments"] += 1
    return counts
