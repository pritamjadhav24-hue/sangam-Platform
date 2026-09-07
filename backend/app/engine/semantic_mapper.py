import re


def parse_income(value) -> int:
    text = str(value).lower().replace(",", "")
    numbers = re.findall(r"[0-9.]+", text)
    amount = float(numbers[0]) if numbers else 0
    return int(amount * 100000) if "lakh" in text else int(amount)


def map_record(requirement: str, record: dict) -> dict:
    if requirement == "INCOME_PROOF": return {"incomeAmount": parse_income(record["annual_income"]), "incomePeriod": "ANNUAL", "currency": "INR"}
    if requirement == "CASTE_PROOF": return {"category": {"OBC": "OTHER_BACKWARD_CLASSES"}.get(record["category"], record["category"])}
    if requirement == "ACADEMIC_RECORD": return {"qualifyingMarks": float(record["qualifying_marks"]), "percentage": float(record["qualifying_marks"])}
    if requirement == "DOMICILE_PROOF": return {"state": record["state"], "domicileStatus": "VERIFIED"}
    if requirement == "BANK_DETAILS": return {"bankStatus": record["accountStatus"]}
    if requirement == "IDENTITY": return {"identityStatus": "VERIFIED"}
    return {}
