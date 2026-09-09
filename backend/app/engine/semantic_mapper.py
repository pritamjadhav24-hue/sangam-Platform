import re


def parse_income(value) -> int:
    text = str(value).lower().replace(",", "")
    numbers = re.findall(r"[0-9.]+", text)
    amount = float(numbers[0]) if numbers else 0
    return int(amount * 100000) if "lakh" in text else int(amount)


def _with_source_reference(record: dict, mapped: dict) -> dict:
    source_reference = record.get("recordId") or record.get("studentId")
    if source_reference:
        mapped["sourceRecordId"] = source_reference
    return mapped


def map_record(requirement: str, record: dict) -> dict:
    if requirement == "INCOME_PROOF": return _with_source_reference(record, {"incomeAmount": parse_income(record["annual_income"]), "incomePeriod": "ANNUAL", "currency": "INR"})
    if requirement == "CASTE_PROOF": return _with_source_reference(record, {"category": {"OBC": "OTHER_BACKWARD_CLASSES"}.get(record["category"], record["category"])})
    if requirement == "ACADEMIC_RECORD": return _with_source_reference(record, {"qualifyingMarks": float(record["qualifying_marks"]), "percentage": float(record["qualifying_marks"])})
    if requirement == "DOMICILE_PROOF": return _with_source_reference(record, {"state": record["state"], "domicileStatus": "VERIFIED"})
    if requirement == "BANK_DETAILS": return _with_source_reference(record, {"bankStatus": record["accountStatus"]})
    if requirement == "IDENTITY": return _with_source_reference(record, {"identityStatus": "VERIFIED"})
    return {}


def mapping_evidence(requirement: str, record: dict, source_system: str, adapter: str) -> list[dict]:
    """Expose the deterministic field-level mapping used by map_record."""
    source_reference = record.get("recordId") or record.get("studentId")
    specs = []
    if source_reference:
        reference_field = "recordId" if record.get("recordId") else "studentId"
        specs.append((reference_field, "sourceRecordId", "identifier alias"))
    if record.get("name"):
        specs.append(("name", "name", "direct"))
    if record.get("dob"):
        specs.append(("dob", "dateOfBirth", "field rename"))
    requirement_specs = {
        "INCOME_PROOF": [("annual_income", "incomeAmount", "parse numeric INR amount")],
        "CASTE_PROOF": [("category", "category", "OBC enum normalization")],
        "ACADEMIC_RECORD": [("qualifying_marks", "qualifyingMarks", "numeric conversion"), ("qualifying_marks", "percentage", "numeric conversion")],
        "DOMICILE_PROOF": [("state", "state", "direct"), ("state", "domicileStatus", "verified-record rule")],
        "BANK_DETAILS": [("accountStatus", "bankStatus", "field rename")],
        "IDENTITY": [],
    }
    specs.extend(requirement_specs.get(requirement, []))
    return [{
        "sourceSystem": source_system,
        "adapter": adapter,
        "sourceField": source_field,
        "canonicalField": canonical_field,
        "mappingType": mapping_type,
        "certainty": "DETERMINISTIC",
        "confidence": 1.0,
        "sourceRecordId": source_reference,
    } for source_field, canonical_field, mapping_type in specs if source_field in record]
