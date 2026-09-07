from app.engine.adapters import CSVFileAdapter, LegacySOAPAdapter, RestAPIAdapter, validate_payload
from app.engine.entity_resolution import resolve
from app.engine.semantic_mapper import map_record
from app.engine.validation_engine import detect_conflicts, validate
from app.mocks import education_dept, revenue_dept, social_welfare_dept

SOURCES = {"IDENTITY": "Civil Registry", "INCOME_PROOF": "Revenue Department", "CASTE_PROOF": "Social Welfare Department", "DOMICILE_PROOF": "Revenue Department", "ACADEMIC_RECORD": "Education Department", "BANK_DETAILS": "Authorized DBT"}


def discover(citizen: dict, simulate_timeout: bool = False) -> dict:
    adapters = {
        "INCOME_PROOF": RestAPIAdapter("Revenue Department", revenue_dept.get_income),
        "CASTE_PROOF": LegacySOAPAdapter("Social Welfare Department", social_welfare_dept.get_caste),
        "DOMICILE_PROOF": RestAPIAdapter("Revenue Department", revenue_dept.get_domicile),
        "ACADEMIC_RECORD": CSVFileAdapter("Education Department", education_dept.get_academic),
        "BANK_DETAILS": RestAPIAdapter("Authorized DBT", social_welfare_dept.get_bank_status),
    }
    requirements, raw_records = [], []
    identity = {"recordId": citizen["citizenId"], "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "validUntil": "2030-12-31", "signature": "CIVIL-SIGNED"}
    fetched = {"record": identity, "attempts": 1, "delayed": False, "adapter": "Federated SSO"}
    for code in ["IDENTITY", "INCOME_PROOF", "CASTE_PROOF", "DOMICILE_PROOF", "ACADEMIC_RECORD", "BANK_DETAILS"]:
        if code != "IDENTITY": fetched = adapters[code].fetch(citizen["citizenId"], simulate_timeout and code == "INCOME_PROOF")
        record = fetched["record"]
        if not record:
            requirements.append({"code": code, "source": SOURCES[code], "status": "MISSING", "action": "Initiate Revenue Domicile Service" if code == "DOMICILE_PROOF" else "Queued connector retry", "adapter": fetched["adapter"]})
            continue
        raw_records.append(record)
        payload = validate_payload(record); resolution = resolve(citizen, record) if record.get("name") else {"status": "MATCH", "score": 1}
        canonical = map_record(code, record); validation = validate(code, canonical, record)
        status = "FOUND" if payload["valid"] and resolution["status"] == "MATCH" and validation["valid"] else "EXCEPTION"
        requirements.append({"code": code, "source": SOURCES[code], "status": status, "recordId": record.get("recordId", record.get("studentId")), "canonical": canonical, "resolution": resolution, "validation": validation, "verifiedOn": record.get("validUntil"), "adapter": fetched["adapter"], "delayed": fetched.get("delayed", False)})
    return {"requirements": requirements, "conflicts": detect_conflicts(raw_records), "resilienceBanner": "Verification temporarily delayed; retrying automatically in background." if any(r.get("delayed") for r in requirements) else None}
