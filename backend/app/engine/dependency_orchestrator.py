from app.core.event_bus import event_bus
from app.mocks.revenue_dept import issue_domicile


def initiate_domicile(citizen_id: str) -> dict:
    record = issue_domicile(citizen_id)
    if not record: return {"success": False, "message": "Domicile service could not issue a record."}
    event_bus.publish("DOMICILE_ISSUED", {"citizenId": citizen_id, "recordId": record["recordId"], "service": "REV-MAHA-101"})
    event_bus.publish("DEPENDENCY_RESOLVED", {"citizenId": citizen_id, "requirement": "DOMICILE_PROOF"})
    return {"success": True, "service": "REV-MAHA-101", "message": "Domicile issued and linked to the scholarship application.", "recordId": record["recordId"]}
