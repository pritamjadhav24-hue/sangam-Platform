"""Transparent local entity matching for simulated department records.

This is deterministic record matching, not identity proofing. Source values are
never replaced; only normalized comparison values are retained in explanations.
"""
from datetime import datetime
from difflib import SequenceMatcher
import re
from typing import Optional

from rapidfuzz.fuzz import token_set_ratio

HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.70
FIELD_WEIGHTS = {"identity_id": 0.35, "name": 0.35, "date_of_birth": 0.20, "phone": 0.10}


def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower())).strip()


def normalize_name(value) -> str:
    return normalize_text(value)


def normalize_date(value) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return normalize_text(text)


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _identity_id_match(citizen: dict, source: dict) -> Optional[bool]:
    citizen_id = citizen.get("citizenId") or citizen.get("identityId")
    source_ids = [source.get(field) for field in ("citizenId", "citizen_id", "identityId", "identity_id")]
    if not citizen_id or not any(source_ids):
        return None
    return citizen_id in source_ids


def _comparison(field: str, candidate, source) -> dict:
    normalizer = {"name": normalize_name, "date_of_birth": normalize_date, "phone": normalize_phone}[field]
    candidate_normalized, source_normalized = normalizer(candidate), normalizer(source)
    if field == "name":
        if candidate_normalized and source_normalized:
            score = 1.0 if candidate_normalized == source_normalized else round(min(token_set_ratio(candidate_normalized, source_normalized) / 100, SequenceMatcher(None, candidate_normalized, source_normalized).ratio()), 3)
        else:
            score = 0.0
    else:
        score = 1.0 if candidate_normalized and candidate_normalized == source_normalized else 0.0
    return {"field": field, "candidatePresent": bool(candidate), "sourcePresent": bool(source), "normalizedMatch": score == 1.0, "score": score, "candidateNormalized": candidate_normalized, "sourceNormalized": source_normalized}


def resolve(citizen: dict, source: dict) -> dict:
    source_system = source.get("sourceSystem") or source.get("department") or source.get("source")
    candidate_record_id = source.get("recordId") or source.get("studentId")
    field_comparisons = []
    id_match = _identity_id_match(citizen, source)
    if id_match is not None:
        field_comparisons.append({"field": "identity_id", "candidatePresent": True, "sourcePresent": True, "normalizedMatch": id_match, "score": 1.0 if id_match else 0.0, "candidateNormalized": "present", "sourceNormalized": "present" if id_match else "different"})
    aliases = {"date_of_birth": ("dob", "dateOfBirth"), "phone": ("phone", "mobile")}
    for field, source_keys in aliases.items():
        candidate_value = citizen.get("dob") if field == "date_of_birth" else citizen.get("phone")
        source_value = next((source.get(key) for key in source_keys if source.get(key) is not None), None)
        if candidate_value is not None or source_value is not None:
            field_comparisons.append(_comparison(field, candidate_value, source_value))
    if citizen.get("name") is not None or source.get("name") is not None:
        field_comparisons.append(_comparison("name", citizen.get("name"), source.get("name")))

    available = [item for item in field_comparisons if item["candidatePresent"] and item["sourcePresent"]]
    if id_match is True:
        score = 1.0
    elif id_match is False:
        score = 0.0
    elif available:
        weights = {item["field"]: FIELD_WEIGHTS[item["field"]] for item in available}
        weight_total = sum(weights.values())
        score = round(sum(item["score"] * weights[item["field"]] for item in available) / weight_total, 3)
    else:
        score = 0.0
    weights_used = {field: round(weight / sum(FIELD_WEIGHTS[item["field"]] for item in available), 3) for item in available for field, weight in [(item["field"], FIELD_WEIGHTS[item["field"]])]} if available and id_match is not False else {}
    matched_fields = [item["field"] for item in field_comparisons if item["score"] >= 1.0]
    if score >= HIGH_CONFIDENCE:
        confidence_level, status, decision = "HIGH", "MATCH", "AUTO_ACCEPT"
    elif score >= MEDIUM_CONFIDENCE:
        confidence_level, status, decision = "MEDIUM", "UNCERTAIN", "REVIEW"
    else:
        confidence_level, status, decision = "LOW", "MISMATCH", "UNRESOLVED"
    return {
        "status": status, "decision": decision, "confidenceLevel": confidence_level, "score": score,
        "nameScore": next((item["score"] for item in field_comparisons if item["field"] == "name"), 0.0),
        "demographicAnchors": len([item for item in matched_fields if item in {"date_of_birth", "phone"}]),
        "matchedFields": matched_fields, "sourceSystem": source_system, "candidateRecordId": candidate_record_id,
        "fieldComparisons": field_comparisons, "weights": weights_used,
        "provenance": {"sourceSystem": source_system, "sourceRecordId": candidate_record_id, "sourceFields": [item["field"] for item in field_comparisons]},
        "explanation": "Identity identifiers take precedence; otherwise available normalized name, date-of-birth, and phone comparisons are weighted and renormalized.",
    }
