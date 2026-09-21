from __future__ import annotations

import random

from app.sandbox.common import case_bucket, record_id, render_synthetic_document
from app.seeds.synthetic_identity_pool import citizens_with_persona, spelling_variant

from .models import DomicileCertificate, IncomeCertificate, LandRecord, ResidentIndex, SyntheticDocument

SEED = 101

TALUKAS = ["Haveli", "Baramati", "Shirur", "Nagpur Rural", "Kalyan", "Kopargaon", "Miraj", "Karveer"]
VILLAGES = ["Wadgaon", "Shivapur", "Kondhwa", "Manchar", "Sinnar", "Pachgaon", "Talegaon", "Bhor"]


def already_seeded(session) -> bool:
    return session.query(ResidentIndex).count() > 0


def seed(session, citizens: list[dict]) -> dict:
    if already_seeded(session):
        return {"skipped": True}
    rng = random.Random(SEED)
    counts = {"residents": 0, "land_records": 0, "domicile_certificates": 0, "income_certificates": 0, "documents": 0}
    sequence = 1
    for citizen in citizens:
        resident_id = record_id("REV", sequence, "RES")
        sequence += 1
        name = citizen["name"]
        if rng.random() < 0.15:
            name = spelling_variant(rng, name)
        resident = ResidentIndex(
            resident_id=resident_id, citizen_ref=citizen["citizenId"], full_name=name,
            dob=citizen["dob"], mobile=citizen["phone"], taluka=rng.choice(TALUKAS), village=rng.choice(VILLAGES),
        )
        session.add(resident)
        counts["residents"] += 1

        if "FARMER" in citizen.get("personas", []):
            bucket = case_bucket(rng)
            if bucket != "MISSING":
                status = {"POSITIVE": "ACTIVE", "PENDING": "UNDER_MUTATION", "FAILURE": "DISPUTED"}[bucket]
                session.add(LandRecord(
                    record_id=record_id("REV", counts["land_records"] + 1, "LAND"),
                    resident_id=resident_id, survey_number=f"{rng.randint(1, 400)}/{rng.randint(1, 9)}",
                    khata_number=str(rng.randint(1000, 9999)), area_hectares=round(rng.uniform(0.4, 6.0), 2),
                    land_type=rng.choice(["Agricultural", "Non-Agricultural"]), status=status,
                ))
                counts["land_records"] += 1

        bucket = case_bucket(rng)
        if bucket != "MISSING":
            status = {"POSITIVE": "ISSUED", "PENDING": "UNDER_VERIFICATION", "FAILURE": "REJECTED"}[bucket]
            cert_id = record_id("REV", counts["domicile_certificates"] + 1, "DOM")
            session.add(DomicileCertificate(
                certificate_id=cert_id, resident_id=resident_id, issued_on="2025-04-01" if status == "ISSUED" else None,
                valid_until="2031-03-31" if status == "ISSUED" else None, status=status,
            ))
            counts["domicile_certificates"] += 1
            if status == "ISSUED":
                session.add(SyntheticDocument(
                    document_id=f"{cert_id}-DOC", owner_reference=resident_id, title="Domicile Certificate",
                    content_type="text/plain", issued_on="2025-04-01",
                    content_text=render_synthetic_document("Domicile Certificate", name, "Revenue Department", {
                        "Certificate No": cert_id, "State": "Maharashtra", "Taluka": resident.taluka,
                    }),
                ))
                counts["documents"] += 1

        if not (citizen["persona"] == "STUDENT" and rng.random() < 0.6):
            bucket = case_bucket(rng)
            if bucket != "MISSING":
                status = {"POSITIVE": "ISSUED", "PENDING": "UNDER_VERIFICATION", "FAILURE": "REJECTED"}[bucket]
                income = round(rng.uniform(80000, 950000), 2) if status == "ISSUED" else None
                session.add(IncomeCertificate(
                    certificate_id=record_id("REV", counts["income_certificates"] + 1, "INC"),
                    resident_id=resident_id, annual_income=income, financial_year="2025-2026", status=status,
                ))
                counts["income_certificates"] += 1
    return counts
