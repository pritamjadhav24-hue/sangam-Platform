try:
    from rapidfuzz.fuzz import token_set_ratio
except ImportError:  # Keeps the prototype inspectable before its venv is initialized.
    from difflib import SequenceMatcher
    def token_set_ratio(left: str, right: str) -> float:
        left_tokens, right_tokens = set(left.lower().replace('.', '').split()), set(right.lower().replace('.', '').split())
        shared = len(left_tokens & right_tokens)
        base = (2 * shared / (len(left_tokens) + len(right_tokens) or 1)) * 100
        return max(base, SequenceMatcher(None, left.lower(), right.lower()).ratio() * 100)


# Prototype thresholds: >= .85 is safe for automatic acceptance, .70-.849 is
# routed to an officer, and below .70 remains unresolved.
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.70


def _identity_id_match(citizen: dict, source: dict) -> bool:
    citizen_id = citizen.get("citizenId")
    source_ids = [source.get(field) for field in ("citizenId", "citizen_id", "identityId", "identity_id", "recordId")]
    return bool(citizen_id and citizen_id in source_ids)


def resolve(citizen: dict, source: dict) -> dict:
    name_score = token_set_ratio(citizen.get("name", ""), source.get("name", "")) / 100
    matched_fields = []
    if _identity_id_match(citizen, source):
        matched_fields.append("identity_id")
    if source.get("name") and source.get("name") == citizen.get("name"):
        matched_fields.append("name")
    if source.get("dob") and source.get("dob") == citizen.get("dob"):
        matched_fields.append("dob")
    if source.get("phone") and source.get("phone") == citizen.get("phone"):
        matched_fields.append("phone")

    if "identity_id" in matched_fields:
        score = 1.0
    else:
        # Keep the existing deterministic weighting: name similarity plus two
        # available identity anchors (DOB and phone).
        score = round(min(1.0, 0.55 * name_score + 0.225 * int("dob" in matched_fields) + 0.225 * int("phone" in matched_fields)), 3)
    if score >= HIGH_CONFIDENCE:
        confidence_level, status, decision = "HIGH", "MATCH", "AUTO_ACCEPT"
    elif score >= MEDIUM_CONFIDENCE:
        confidence_level, status, decision = "MEDIUM", "UNCERTAIN", "REVIEW"
    else:
        confidence_level, status, decision = "LOW", "MISMATCH", "UNRESOLVED"
    return {
        "status": status,
        "decision": decision,
        "confidenceLevel": confidence_level,
        "score": score,
        "nameScore": round(name_score, 3),
        "demographicAnchors": int("dob" in matched_fields) + int("phone" in matched_fields),
        "matchedFields": matched_fields,
    }
