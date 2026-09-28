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
FIELD_WEIGHTS = {"identity_id": 0.35, "name": 0.35, "date_of_birth": 0.20, "phone": 0.10, "address": 0.10}

# Common Indian address abbreviations -> one canonical spelling, so
# "12, Mahatma Gandhi Rd., Andheri(W)" and "12 MG Road, Andheri West"
# compare equal. Purely local: no geocoding service is required.
ADDRESS_ABBREVIATIONS = {
    "rd": "road", "st": "street", "ln": "lane", "marg": "road", "mg": "mahatma gandhi", "nr": "near", "opp": "opposite",
    "w": "west", "e": "east", "n": "north", "bldg": "building", "apt": "apartment", "apts": "apartment", "soc": "society",
    "chs": "society", "sec": "sector", "stn": "station", "tal": "taluka", "dist": "district", "hsg": "housing",
}
ADDRESS_NOISE = {"no", "number", "house", "flat", "plot", "at", "post", "po", "the", "and"}


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


def normalize_address(value) -> str:
    """Lower-case, strip punctuation, expand abbreviations and drop filler
    words ("No.", "House", ...). A 6-digit PIN code is kept."""
    words = normalize_text(str(value or "").replace("(", " ").replace(")", " ")).split()
    expanded = []
    for word in words:
        replacement = ADDRESS_ABBREVIATIONS.get(word, word)
        expanded.extend(replacement.split())
    return " ".join(word for word in expanded if word not in ADDRESS_NOISE)


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
    normalizer = {"name": normalize_name, "date_of_birth": normalize_date, "phone": normalize_phone, "address": normalize_address}[field]
    candidate_normalized, source_normalized = normalizer(candidate), normalizer(source)
    if field == "name":
        if candidate_normalized and source_normalized:
            if candidate_normalized == source_normalized or sorted(candidate_normalized.split()) == sorted(source_normalized.split()):
                score = 1.0  # same name, possibly in another order ("Kumar Rahul")
            else:
                score = round(min(token_set_ratio(candidate_normalized, source_normalized) / 100, SequenceMatcher(None, candidate_normalized, source_normalized).ratio()), 3)
        else:
            score = 0.0
    elif field == "address":
        # One address may carry more detail (PIN code, landmark) than the other.
        score = round(token_set_ratio(candidate_normalized, source_normalized) / 100, 3) if candidate_normalized and source_normalized else 0.0
        score = 1.0 if score >= 0.9 else score
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
    aliases = {"date_of_birth": ("dob", "dateOfBirth"), "phone": ("phone", "mobile"), "address": ("address",)}
    for field, source_keys in aliases.items():
        candidate_value = citizen.get({"date_of_birth": "dob", "phone": "phone", "address": "address"}[field])
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
        "explanation": "Identity identifiers take precedence; otherwise available normalized name, date-of-birth, phone and address comparisons are weighted and renormalized.",
    }


# Department records name their identity fields differently.
DEPARTMENT_IDENTITY_FIELDS = {
    "name": ("resident_name", "student_name", "beneficiary_name", "name", "farmer_name", "applicant_name"),
    "dob": ("dob", "date_of_birth"),
    "phone": ("mobile", "phone", "guardian_mobile"),
    "address": ("address", "address_line"),
}


def department_identity(raw: dict) -> dict:
    identity = {}
    for field, keys in DEPARTMENT_IDENTITY_FIELDS.items():
        value = next((raw.get(key) for key in keys if raw.get(key) not in (None, "")), None)
        if value is not None:
            identity[field] = value
    return identity


def citizen_identity(citizen_id: str) -> dict:
    """The citizen's identity as SANGAM holds it (platform citizen master,
    then the account profile)."""
    from sqlalchemy.orm import Session
    from app.core.persistence import CitizenRow, UserAccountRow, engine
    with Session(engine) as session:
        row = session.get(CitizenRow, citizen_id)
        if row is not None:
            return {"citizenId": citizen_id, "name": row.full_name, "dob": row.date_of_birth, "phone": row.phone,
                    "address": (row.payload or {}).get("address")}
        account = session.get(UserAccountRow, citizen_id)
        payload = (account.payload if account else None) or {}
        return {"citizenId": citizen_id, "name": payload.get("name"), "dob": payload.get("dob"), "phone": payload.get("phone"),
                "address": payload.get("address")}


def match_department_record(citizen: dict, raw: dict, source_system: Optional[str] = None) -> Optional[dict]:
    """Is this department record the same person as the citizen?

    Demographics only -- the department indexed the record under SANGAM's
    citizen reference, so that reference cannot also be the evidence.
    Returns None when the record carries no comparable identity field."""
    identity = department_identity(raw or {})
    if not identity or not any(citizen.get(key) for key in ("name", "dob", "phone")):
        return None
    candidate = {key: citizen.get(key) for key in ("name", "dob", "phone", "address") if citizen.get(key)}
    source = {key: identity.get(key) for key in ("name", "dob", "phone", "address") if key in identity}
    return resolve(candidate, {**source, "sourceSystem": source_system})


# How sure SANGAM is that a department record is this citizen's -- the
# existing confidence model, named for the citizen and officer views.
MATCH_CATEGORIES = {"EXACT": "Exact match", "STRONG": "Strong match", "PROBABLE": "Probable match", "NO_MATCH": "No match"}


def match_category(match: Optional[dict], department_method: Optional[str] = None) -> str:
    """EXACT: the department identified the person by an identifier (its own,
    or the SANGAM cross-reference it holds) and every compared attribute
    agrees. STRONG: high-confidence demographic match. PROBABLE: medium
    confidence (never auto-filled). NO_MATCH: anything lower."""
    if not match:
        return "NO_MATCH"
    if match.get("decision") == "AUTO_ACCEPT":
        identified = department_method in {"DEPARTMENT_IDENTIFIER", "CROSS_REFERENCE"}
        return "EXACT" if identified and match.get("score") == 1.0 else "STRONG"
    return "PROBABLE" if match.get("decision") == "REVIEW" else "NO_MATCH"
