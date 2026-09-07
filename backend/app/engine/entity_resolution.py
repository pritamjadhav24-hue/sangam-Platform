try:
    from rapidfuzz.fuzz import token_set_ratio
except ImportError:  # Keeps the prototype inspectable before its venv is initialized.
    from difflib import SequenceMatcher
    def token_set_ratio(left: str, right: str) -> float:
        left_tokens, right_tokens = set(left.lower().replace('.', '').split()), set(right.lower().replace('.', '').split())
        shared = len(left_tokens & right_tokens)
        base = (2 * shared / (len(left_tokens) + len(right_tokens) or 1)) * 100
        return max(base, SequenceMatcher(None, left.lower(), right.lower()).ratio() * 100)


def resolve(citizen: dict, source: dict) -> dict:
    name_score = token_set_ratio(citizen.get("name", ""), source.get("name", "")) / 100
    # Strong demographic anchors intentionally outweigh an abbreviation in a name.
    anchors = sum([source.get("dob") == citizen.get("dob"), source.get("phone") == citizen.get("phone")])
    score = round(min(1.0, 0.55 * name_score + 0.225 * anchors), 3)
    status = "MATCH" if score >= .85 else "UNCERTAIN" if score >= .70 else "MISMATCH"
    return {"status": status, "score": score, "nameScore": round(name_score, 3), "demographicAnchors": anchors}
