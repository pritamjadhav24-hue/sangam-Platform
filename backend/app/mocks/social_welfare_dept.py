CASTE_RECORD = {"recordId": "SW-443", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "category": "OBC", "validUntil": "2028-03-31", "signature": "SW-SIGNED"}
BANK_RECORD = {"recordId": "DBT-661", "accountStatus": "VERIFIED", "validUntil": "2027-03-31", "signature": "DBT-SIGNED"}


def get_caste(citizen_id: str):
    return CASTE_RECORD.copy() if citizen_id == "CITIZEN_001" else None


def get_bank_status(citizen_id: str):
    return BANK_RECORD.copy() if citizen_id == "CITIZEN_001" else None
