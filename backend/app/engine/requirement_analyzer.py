from __future__ import annotations

from app.engine.adapters import CSVFileAdapter, LegacySOAPAdapter, RestAPIAdapter, validate_payload
from app.engine.entity_resolution import resolve
from app.engine import semantic_mapper
from app.engine.registry import get_scheme
from app.engine.semantic_mapper import map_record, mapping_evidence
from app.engine.validation_engine import detect_canonical_conflicts, detect_conflicts, validate
from app.mocks import education_dept, revenue_dept, social_welfare_dept

SOURCES = {"IDENTITY": "Civil Registry", "INCOME_PROOF": "Revenue Department", "CASTE_PROOF": "Social Welfare Department", "DOMICILE_PROOF": "Revenue Department", "ACADEMIC_RECORD": "Education Department", "BANK_DETAILS": "Authorized DBT"}


def discover(citizen: dict, simulate_timeout: bool = False, scheme_id: str | None = None) -> dict:
    adapters = {
        "INCOME_PROOF": RestAPIAdapter("Revenue Department", revenue_dept.get_income),
        "CASTE_PROOF": LegacySOAPAdapter("Social Welfare Department", social_welfare_dept.get_caste),
        "DOMICILE_PROOF": RestAPIAdapter("Revenue Department", revenue_dept.get_domicile),
        "ACADEMIC_RECORD": CSVFileAdapter("Education Department", education_dept.get_academic),
        "BANK_DETAILS": RestAPIAdapter("Authorized DBT", social_welfare_dept.get_bank_status),
    }
    requirements, raw_records, mapping_records, source_records = [], [], [], []
    identity = {"recordId": citizen["citizenId"], "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "validUntil": "2030-12-31", "signature": "CIVIL-SIGNED"}
    fetched = {"record": identity, "attempts": 1, "delayed": False, "adapter": "Federated SSO"}
    scheme = get_scheme(scheme_id) if scheme_id else None
    if scheme is None:
        from app.core.persistence import catalog_snapshot
        configured = catalog_snapshot()["schemes"]
        scheme = configured[0] if configured else {"requirements": [{"code": code} for code in ["IDENTITY", "INCOME_PROOF", "CASTE_PROOF", "DOMICILE_PROOF", "ACADEMIC_RECORD", "BANK_DETAILS"]]}
    configured_codes = [item["code"] for item in scheme.get("requirements", [])]
    for code in configured_codes:
        source = SOURCES.get(code, "Configured provider")
        adapter = adapters.get(code)
        if code != "IDENTITY":
            fetched = adapter.fetch(citizen["citizenId"], simulate_timeout and code == "INCOME_PROOF") if adapter else {"record": None, "attempts": 0, "delayed": False, "adapter": "Unregistered adapter"}
        record = fetched["record"]
        if not record:
            requirements.append({"code": code, "source": source, "status": "MISSING", "action": "Select a registered provider" if not adapter else "Queued connector retry", "adapter": fetched["adapter"]})
            continue
        raw_records.append(record)
        source_records.append({"sourceSystem": source, "sourceRecordId": record.get("recordId", record.get("studentId")), "adapter": fetched["adapter"], "record": record})
        payload = validate_payload(record); resolution = resolve(citizen, {**record, "sourceSystem": source}) if record.get("name") else {"status": "MATCH", "decision": "AUTO_ACCEPT", "confidenceLevel": "HIGH", "score": 1, "matchedFields": ["source-record-verified"], "fieldComparisons": [], "weights": {}, "sourceSystem": source, "candidateRecordId": record.get("recordId", record.get("studentId"))}
        canonical = map_record(code, record); validation = validate(code, canonical, record)
        mappings = mapping_evidence(code, record, source, fetched["adapter"])
        mapping_records.extend(mappings)
        status = "FOUND" if payload["valid"] and resolution["decision"] == "AUTO_ACCEPT" and validation["valid"] else "REVIEW_REQUIRED" if resolution["decision"] == "REVIEW" else "UNRESOLVED"
        record_id = record.get("recordId", record.get("studentId"))
        requirements.append({"code": code, "source": source, "status": status, "recordId": record_id, "canonical": canonical, "provenance": {"sourceSystem": source, "adapter": fetched["adapter"], "sourceRecordId": record_id}, "mappingEvidence": mappings, "resolution": resolution, "validation": validation, "verifiedOn": record.get("validUntil"), "adapter": fetched["adapter"], "delayed": fetched.get("delayed", False)})
    return {"schemeId": scheme.get("id"), "requirements": requirements, "mappingMode": "HYBRID_DETERMINISTIC_PLUS_LOCAL_AI", "mappingEvidence": mapping_records, "semanticMappingEvidence": semantic_mapper.current_schema_evidence(), "conflicts": detect_canonical_conflicts(source_records), "legacyConflictMessages": detect_conflicts(raw_records), "resilienceBanner": "Verification temporarily delayed; retrying automatically in background." if any(r.get("delayed") for r in requirements) else None}
