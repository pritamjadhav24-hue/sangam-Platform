EDUCATION_RECORD = {"studentId": "S892", "name": "Rahul K.", "dob": "2005-06-15", "phone": "+91-9876543210", "qualifying_marks": "82.5", "familyAnnualIncome": "450000", "validUntil": "2027-06-30", "signature": "EDU-SIGNED"}
_ORIGINAL_FAMILY_INCOME = EDUCATION_RECORD["familyAnnualIncome"]


def get_academic(citizen_id: str):
    return EDUCATION_RECORD.copy() if citizen_id == "CITIZEN_001" else None


def set_income_conflict(enabled: bool):
    EDUCATION_RECORD["familyAnnualIncome"] = "550000" if enabled else _ORIGINAL_FAMILY_INCOME
    return EDUCATION_RECORD["familyAnnualIncome"]
