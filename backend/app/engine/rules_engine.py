def evaluate(requirements: list[dict]) -> dict:
    values = {r["code"]: r.get("canonical", {}) for r in requirements}
    reasons = []
    income = values.get("INCOME_PROOF", {}).get("incomeAmount")
    marks = values.get("ACADEMIC_RECORD", {}).get("percentage")
    missing = [r["code"] for r in requirements if r["status"] != "FOUND"]
    if missing: reasons.append(f"Required verification incomplete: {', '.join(missing)}")
    if income is not None and income > 600000: reasons.append("Family income exceeds the ₹6,00,000 annual limit.")
    if marks is not None and marks < 60: reasons.append("Qualifying academic score is below 60%.")
    return {"eligible": not reasons, "reasons": reasons, "incomeLimit": 600000, "minimumMarks": 60}
