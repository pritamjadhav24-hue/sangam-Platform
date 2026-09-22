from app.mocks._citizen_lookup import lookup_citizen, stable_choice

CASTE_RECORD = {"recordId": "SW-443", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "category": "OBC", "validUntil": "2028-03-31", "signature": "SW-SIGNED"}
BANK_RECORD = {"recordId": "DBT-661", "accountStatus": "VERIFIED", "validUntil": "2027-03-31", "signature": "DBT-SIGNED"}
_CASTE_CATEGORIES = ["OBC", "OPEN", "SC", "ST", "NT"]


def get_caste(citizen_id: str):
    if citizen_id == "CITIZEN_001":
        return CASTE_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    category = _CASTE_CATEGORIES[stable_choice(citizen_id, "caste", 0, len(_CASTE_CATEGORIES) - 1)]
    return {"recordId": f"SW-{citizen_id}", "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "category": category, "validUntil": "2028-03-31", "signature": "SW-SIGNED"}


def get_bank_status(citizen_id: str):
    if citizen_id == "CITIZEN_001":
        return BANK_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    return {"recordId": f"DBT-{citizen_id}", "accountStatus": "VERIFIED", "validUntil": "2027-03-31", "signature": "DBT-SIGNED"}
