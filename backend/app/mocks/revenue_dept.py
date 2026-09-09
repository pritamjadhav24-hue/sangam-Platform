from datetime import date

from app.engine.adapters import is_integration_available

REVENUE_RECORD = {"recordId": "R102", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "annual_income": "450000", "validUntil": "2027-03-31", "signature": "REV-SIGNED"}
DOMICILE_RECORD = None


def get_income(citizen_id: str):
    return REVENUE_RECORD.copy() if citizen_id == "CITIZEN_001" else None


def get_domicile(citizen_id: str):
    return DOMICILE_RECORD.copy() if citizen_id == "CITIZEN_001" and DOMICILE_RECORD else None


def issue_domicile(citizen_id: str):
    global DOMICILE_RECORD
    if citizen_id != "CITIZEN_001" or not is_integration_available("Revenue Department"):
        return None
    DOMICILE_RECORD = {"recordId": "D-MH-9001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "state": "Maharashtra", "issuedOn": str(date.today()), "validUntil": "2031-03-31", "signature": "REV-DOMICILE-SIGNED"}
    return DOMICILE_RECORD.copy()
