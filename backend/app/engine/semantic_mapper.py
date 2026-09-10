"""Canonical mapping plus a local metadata-only suggestion layer."""
from datetime import datetime, timezone
import re
from typing import Optional

from rapidfuzz.fuzz import token_set_ratio

AI_HIGH_THRESHOLD = 0.85
AI_MEDIUM_THRESHOLD = 0.70

CANONICAL_FIELDS = {
    "name": {"description": "person's full name", "aliases": {"name", "full name", "applicant name", "resident name", "student full name"}},
    "dateOfBirth": {"description": "date of birth", "aliases": {"dob", "birth date", "date of birth"}},
    "incomeAmount": {"description": "annual household income in INR", "aliases": {"income", "annual income", "parent income", "family annual income"}},
    "percentage": {"description": "academic marks percentage", "aliases": {"marks percentage", "percentage", "qualifying marks"}},
    "state": {"description": "domicile state", "aliases": {"state", "domicile state"}},
    "sourceRecordId": {"description": "department source record reference", "aliases": {"record id", "domicile number", "domicile certificate"}},
}
DETERMINISTIC_ALIASES = {
    "annual_income": "incomeAmount", "familyAnnualIncome": "incomeAmount", "parent_income": "incomeAmount", "income": "incomeAmount",
    "name": "name", "resident_name": "name", "student_full_name": "name", "applicant_name": "name",
    "dob": "dateOfBirth", "birth_date": "dateOfBirth", "date_of_birth": "dateOfBirth",
    "qualifying_marks": "percentage", "marks_percentage": "percentage", "state": "state", "domicile_state": "state", "domicile_no": "sourceRecordId",
}
MAPPING_REVIEWS: dict[str, dict] = {}
MAPPING_REVIEW_COUNTER = 1


def _tokens(value: str) -> set[str]:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    return {token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if token}


def _level(confidence: float) -> str:
    return "HIGH" if confidence >= AI_HIGH_THRESHOLD else "MEDIUM" if confidence >= AI_MEDIUM_THRESHOLD else "LOW"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def deterministic_field_mapping(source_field: str) -> Optional[str]:
    return DETERMINISTIC_ALIASES.get(source_field)


def ai_suggest_mapping(source_system: str, source_field: str, source_datatype: str = "string", source_description: str = "", canonical_candidates: Optional[list[str]] = None, canonical_descriptions: Optional[dict[str, str]] = None) -> dict:
    """Suggest from schema metadata only; no citizen record or external service is used."""
    candidates = canonical_candidates or list(CANONICAL_FIELDS)
    descriptions = canonical_descriptions or {field: details["description"] for field, details in CANONICAL_FIELDS.items()}
    field_text = " ".join(sorted(_tokens(source_field) | _tokens(source_description)))
    best_field, best_score, best_reason = None, 0.45, "No strong local semantic evidence was found."
    for candidate in candidates:
        aliases = set(CANONICAL_FIELDS.get(candidate, {}).get("aliases", set())) | {candidate, descriptions.get(candidate, "")}
        score = max([token_set_ratio(field_text, " ".join(sorted(_tokens(alias)))) / 100 for alias in aliases if alias] or [0.0])
        if source_field in DETERMINISTIC_ALIASES and DETERMINISTIC_ALIASES[source_field] == candidate:
            score = max(score, 0.96)
        if score > best_score:
            best_field, best_score = candidate, min(score, 0.99)
            best_reason = f"Local token/alias similarity between '{source_field}' and '{candidate}'."
    confidence = round(best_score, 3)
    level = _level(confidence)
    return {"sourceSystem": source_system, "sourceField": source_field, "sourceDatatype": source_datatype, "canonicalField": best_field, "mappingMode": "AI_SUGGESTED", "confidence": confidence, "confidenceLevel": level, "evidence": best_reason, "reason": best_reason, "transformation": "metadata-only semantic alias suggestion", "humanReviewRequired": level != "HIGH", "timestamp": _timestamp()}


def hybrid_mapping(source_system: str, source_field: str, source_datatype: str = "string", source_description: str = "", deterministic_field: Optional[str] = None) -> dict:
    deterministic = deterministic_field or deterministic_field_mapping(source_field)
    suggestion = ai_suggest_mapping(source_system, source_field, source_datatype, source_description)
    if deterministic:
        suggestion["alternativeSuggestion"] = {"canonicalField": suggestion["canonicalField"], "confidence": suggestion["confidence"], "mappingMode": suggestion["mappingMode"], "evidence": suggestion["evidence"]}
        return {**suggestion, "canonicalField": deterministic, "mappingMode": "DETERMINISTIC_CANONICAL_RULES", "confidence": 1.0, "confidenceLevel": "HIGH", "evidence": "Exact canonical mapping rule matched; deterministic result is authoritative.", "humanReviewRequired": False, "transformation": "existing deterministic canonical rule"}
    return suggestion


def create_mapping_review(mapping: dict, correlation_id: Optional[str] = None) -> dict:
    global MAPPING_REVIEW_COUNTER
    if not mapping.get("humanReviewRequired"):
        return mapping
    review_id = f"MAP-REVIEW-{MAPPING_REVIEW_COUNTER:04d}"
    MAPPING_REVIEW_COUNTER += 1
    review = {"reviewId": review_id, "status": "WAITING_FOR_OFFICER", "correlationId": correlation_id, "mapping": mapping, "createdAt": _timestamp(), "updatedAt": _timestamp()}
    MAPPING_REVIEWS[review_id] = review
    return {**mapping, "reviewId": review_id, "reviewStatus": review["status"]}


def decide_mapping_review(review_id: str, decision: str, actor_id: str, actor_role: str, remarks: str) -> dict:
    if actor_role not in {"OFFICER", "ADMIN"}:
        raise PermissionError("Only officers or administrators may decide schema mapping reviews.")
    if decision not in {"APPROVE", "REJECT"} or not remarks.strip():
        raise ValueError("Mapping review requires APPROVE or REJECT and mandatory remarks.")
    review = MAPPING_REVIEWS.get(review_id)
    if not review:
        raise KeyError("Schema mapping review not found.")
    if review["status"] != "WAITING_FOR_OFFICER":
        if review.get("decision") == decision:
            return review
        raise ValueError("Schema mapping review has already been decided.")
    review.update({"status": "APPROVED" if decision == "APPROVE" else "REJECTED", "decision": decision, "actorId": actor_id, "actorRole": actor_role, "remarks": remarks, "updatedAt": _timestamp()})
    if decision == "APPROVE":
        review["approvedMapping"] = {**review["mapping"], "mappingMode": "HUMAN_APPROVED", "humanReviewRequired": False, "approvedBy": actor_id}
    return review


def simulated_schema_evidence() -> list[dict]:
    examples = [("Revenue Department (simulated)", "annual_income", "number", "annual household income", "incomeAmount"), ("Education Department (simulated)", "parent_income", "number", "family annual income used for scholarship", "incomeAmount"), ("Revenue Department (simulated)", "resident_name", "string", "name of resident", "name"), ("Education Department (simulated)", "dob", "date", "student date of birth", "dateOfBirth"), ("Revenue Department (simulated)", "unknown_earnings_value", "number", "annual earnings value", None)]
    results = []
    for system, field, datatype, description, deterministic in examples:
        result = hybrid_mapping(system, field, datatype, description, deterministic)
        if result["mappingMode"] == "AI_SUGGESTED" and result["humanReviewRequired"]:
            result = create_mapping_review(result)
        results.append(result)
    return results


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
    source_reference = record.get("recordId") or record.get("studentId")
    specs = []
    if source_reference:
        reference_field = "recordId" if record.get("recordId") else "studentId"
        specs.append((reference_field, "sourceRecordId", "identifier alias"))
    if record.get("name"): specs.append(("name", "name", "direct"))
    if record.get("dob"): specs.append(("dob", "dateOfBirth", "field rename"))
    specs.extend({"INCOME_PROOF": [("annual_income", "incomeAmount", "parse numeric INR amount")], "CASTE_PROOF": [("category", "category", "OBC enum normalization")], "ACADEMIC_RECORD": [("qualifying_marks", "qualifyingMarks", "numeric conversion"), ("qualifying_marks", "percentage", "numeric conversion"), ("familyAnnualIncome", "incomeAmount", "parse numeric INR amount")], "DOMICILE_PROOF": [("state", "state", "direct"), ("state", "domicileStatus", "verified-record rule")], "BANK_DETAILS": [("accountStatus", "bankStatus", "field rename")], "IDENTITY": []}.get(requirement, []))
    return [{"sourceSystem": source_system, "adapter": adapter, "sourceField": source_field, "canonicalField": canonical_field, "mappingType": mapping_type, "mappingMode": "DETERMINISTIC_CANONICAL_RULES", "certainty": "DETERMINISTIC", "confidence": 1.0, "evidence": "Existing canonical field rule.", "transformation": mapping_type, "sourceRecordId": source_reference, "timestamp": _timestamp()} for source_field, canonical_field, mapping_type in specs if source_field in record]


SIMULATED_SCHEMA_EVIDENCE = simulated_schema_evidence()


def reset_mapping_state() -> None:
    global MAPPING_REVIEW_COUNTER, SIMULATED_SCHEMA_EVIDENCE
    MAPPING_REVIEWS.clear()
    MAPPING_REVIEW_COUNTER = 1
    SIMULATED_SCHEMA_EVIDENCE = simulated_schema_evidence()


def current_schema_evidence() -> list[dict]:
    evidence = []
    for item in SIMULATED_SCHEMA_EVIDENCE:
        review = MAPPING_REVIEWS.get(item.get("reviewId"))
        if review:
            evidence.append({**item, "reviewStatus": review["status"], "decision": review.get("decision"), "approvedMapping": review.get("approvedMapping")})
        else:
            evidence.append(item)
    return evidence
