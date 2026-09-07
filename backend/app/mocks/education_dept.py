EDUCATION_RECORD = {"studentId": "S892", "name": "Rahul K.", "dob": "2005-06-15", "phone": "+91-9876543210", "qualifying_marks": "82.5", "validUntil": "2027-06-30", "signature": "EDU-SIGNED"}


def get_academic(citizen_id: str):
    return EDUCATION_RECORD.copy() if citizen_id == "CITIZEN_001" else None
