from datetime import date


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
