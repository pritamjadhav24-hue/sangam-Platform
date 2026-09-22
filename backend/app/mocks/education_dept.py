from app.mocks._citizen_lookup import lookup_citizen, stable_choice

EDUCATION_RECORD = {"studentId": "S892", "name": "Rahul K.", "dob": "2005-06-15", "phone": "+91-9876543210", "qualifying_marks": "82.5", "familyAnnualIncome": "450000", "validUntil": "2027-06-30", "signature": "EDU-SIGNED"}
_ORIGINAL_FAMILY_INCOME = EDUCATION_RECORD["familyAnnualIncome"]


def get_academic(citizen_id: str):
    if citizen_id == "CITIZEN_001":
        return EDUCATION_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    marks = stable_choice(citizen_id, "marks", 45, 95)
    income = stable_choice(citizen_id, "income", 120000, 620000)
    return {"studentId": f"S-{citizen_id}", "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "qualifying_marks": str(marks), "familyAnnualIncome": str(income), "validUntil": "2027-06-30", "signature": "EDU-SIGNED"}


def set_income_conflict(enabled: bool):
    EDUCATION_RECORD["familyAnnualIncome"] = "550000" if enabled else _ORIGINAL_FAMILY_INCOME
    return EDUCATION_RECORD["familyAnnualIncome"]
