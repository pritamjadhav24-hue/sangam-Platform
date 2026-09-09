from datetime import date, datetime, timezone
import re


def validate(requirement: str, canonical: dict, source: dict) -> dict:
    reasons = []
    if not canonical: reasons.append("Incomplete canonical attribute")
    if source.get("validUntil") and source["validUntil"] < str(date.today()): reasons.append("Source credential expired")
    if requirement == "INCOME_PROOF" and canonical.get("incomeAmount", 0) < 0: reasons.append("Income cannot be negative")
    if requirement == "ACADEMIC_RECORD" and not 0 <= canonical.get("percentage", -1) <= 100: reasons.append("Marks must be between 0 and 100")
    return {"valid": not reasons, "reasons": reasons}


def detect_conflicts(records: list[dict]) -> list[str]:
    dobs = {r.get("dob") for r in records if r and r.get("dob")}
    return ["DOB conflict across federated sources; routed for authority review"] if len(dobs) > 1 else []


def _income_amount(value) -> int:
    numbers = re.findall(r"[0-9.]+", str(value).lower().replace(",", ""))
    amount = float(numbers[0]) if numbers else 0
    return int(amount * 100000) if "lakh" in str(value).lower() else int(amount)


def detect_canonical_conflicts(source_records: list[dict]) -> list[dict]:
    """Compare deterministic canonical values from trusted source snapshots."""
    candidates = {}
    for item in source_records:
        record = item["record"]
        if record.get("annual_income") is not None:
            candidates.setdefault("incomeAmount", []).append({**item, "value": _income_amount(record["annual_income"]), "sourceField": "annual_income"})
        if record.get("familyAnnualIncome") is not None:
            candidates.setdefault("incomeAmount", []).append({**item, "value": _income_amount(record["familyAnnualIncome"]), "sourceField": "familyAnnualIncome"})
        if record.get("dob"):
            candidates.setdefault("dateOfBirth", []).append({**item, "value": record["dob"], "sourceField": "dob"})

    conflicts = []
    for canonical_field, values in candidates.items():
        distinct = {str(item["value"]) for item in values}
        if len(distinct) < 2 or len({item["sourceSystem"] for item in values}) < 2:
            continue
        conflicts.append({
            "canonicalField": canonical_field,
            "requirementCode": "INCOME_PROOF" if canonical_field == "incomeAmount" else "IDENTITY",
            "sources": [{"sourceSystem": item["sourceSystem"], "sourceRecordId": item.get("sourceRecordId"), "sourceField": item["sourceField"], "value": item["value"]} for item in values],
            "status": "DETECTED",
            "detectedAt": datetime.now(timezone.utc).isoformat(),
        })
    return conflicts
