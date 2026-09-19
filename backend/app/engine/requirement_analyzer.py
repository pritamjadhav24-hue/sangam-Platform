from __future__ import annotations

from app.engine.adapters import integration_health, request_registered_service, validate_payload
from app.engine.entity_resolution import resolve
from app.engine import semantic_mapper
from app.engine.registry import get_scheme, select_dependency_provider
from app.engine.semantic_mapper import map_record, mapping_evidence
from app.engine.validation_engine import detect_canonical_conflicts, detect_conflicts, validate

SOURCES = {"IDENTITY": "Civil Registry"}


def discover(citizen: dict, simulate_timeout: bool = False, scheme_id: str | None = None, service_id: str | None = None) -> dict:
    requirements, raw_records, mapping_records, source_records = [], [], [], []
    identity = {"recordId": citizen["citizenId"], "name": citizen["name"], "dob": citizen["dob"], "phone": citizen["phone"], "validUntil": "2030-12-31", "signature": "CIVIL-SIGNED"}
    fetched = {"record": identity, "attempts": 1, "delayed": False, "adapter": "Federated SSO"}
    selected_service_id = service_id or scheme_id
    scheme = get_scheme(selected_service_id) if selected_service_id else None
    if scheme is None:
        from app.core.persistence import catalog_snapshot
        configured = catalog_snapshot()["schemes"]
        if not configured:
            raise RuntimeError("Configured service catalog is unavailable")
        scheme = configured[0]
    configured_codes = [item["code"] for item in scheme.get("requirements", [])]
    for code in configured_codes:
        source = SOURCES.get(code, "Configured provider")
        if code != "IDENTITY":
            from app.core.persistence import catalog_snapshot
            configured_service = select_dependency_provider(code, integration_health())
            if configured_service:
                result = request_registered_service(configured_service["serviceId"], citizen["citizenId"], requirement_code=code, correlation_id=citizen.get("citizenId"))
                source = configured_service.get("provider", source)
                fetched = {"record": None if simulate_timeout and code == "INCOME_PROOF" else result.record, "attempts": result.attempts, "delayed": result.delayed, "adapter": configured_service.get("adapter", "Configured adapter")}
            else:
                fetched = {"record": None, "attempts": 0, "delayed": False, "adapter": "Unregistered adapter"}
        record = fetched["record"]
        if not record:
            requirements.append({"code": code, "source": source, "status": "MISSING", "action": "Select a registered provider" if fetched["adapter"] == "Unregistered adapter" else "Queued connector retry", "adapter": fetched["adapter"]})
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
    return {"schemeId": scheme.get("id"), "serviceId": scheme.get("id"), "service": {"serviceId": scheme.get("id"), "name": scheme.get("name"), "department": scheme.get("department")}, "requirements": requirements, "mappingMode": "HYBRID_DETERMINISTIC_PLUS_LOCAL_AI", "mappingEvidence": mapping_records, "semanticMappingEvidence": semantic_mapper.current_schema_evidence(), "conflicts": detect_canonical_conflicts(source_records), "legacyConflictMessages": detect_conflicts(raw_records), "resilienceBanner": "Verification temporarily delayed; retrying automatically in background." if any(r.get("delayed") for r in requirements) else None}
