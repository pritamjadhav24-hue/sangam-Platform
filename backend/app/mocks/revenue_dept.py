from datetime import date

from app.engine.adapters import is_integration_available
from app.mocks._citizen_lookup import lookup_citizen, stable_choice

REVENUE_RECORD = {"recordId": "R102", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "annual_income": "450000", "validUntil": "2027-03-31", "signature": "REV-SIGNED"}
DOMICILE_RECORD = None


def get_income(citizen_id: str):
    if citizen_id == "CITIZEN_001":
        return REVENUE_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    amount = stable_choice(citizen_id, "income", 120000, 620000)
    return {"recordId": f"R-{citizen_id}", "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "annual_income": str(amount), "validUntil": "2027-03-31", "signature": "REV-SIGNED"}


def get_domicile(citizen_id: str):
    return DOMICILE_RECORD.copy() if citizen_id == "CITIZEN_001" and DOMICILE_RECORD else None


def issue_domicile(citizen_id: str):
    global DOMICILE_RECORD
    if not is_integration_available("Revenue Department"):
        return None
    if citizen_id == "CITIZEN_001":
        DOMICILE_RECORD = {"recordId": "D-MH-9001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "state": "Maharashtra", "issuedOn": str(date.today()), "validUntil": "2031-03-31", "signature": "REV-DOMICILE-SIGNED"}
        return DOMICILE_RECORD.copy()
    citizen = lookup_citizen(citizen_id)
    if not citizen:
        return None
    return {"recordId": f"D-MH-{citizen_id}", "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "state": "Maharashtra", "issuedOn": str(date.today()), "validUntil": "2031-03-31", "signature": "REV-DOMICILE-SIGNED"}
