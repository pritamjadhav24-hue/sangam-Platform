"""Deterministic scheme eligibility.

Each scheme declares its criteria as ``eligibilityRules`` in its catalog
payload (seeded from app.engine.registry.SCHEMES). Every rule evaluates to
PASS, FAIL or UNKNOWN using only data SANGAM actually holds for the
application: requirement results verified through a provider, documents the
citizen supplied, and the citizen's platform identity record. There is no
score -- the outcome is:

- NOT_ELIGIBLE     at least one rule FAILED on verified data;
- CANNOT_CONFIRM   nothing failed, but some rule could not be evaluated
                   (missing, unverified, rejected/expired or conflicting data);
- ELIGIBLE         every rule PASSED.

A rule is never failed on missing or unverified data: that is always
UNKNOWN, so a citizen is never wrongly declared ineligible. Admins also get
data-completeness figures and a High/Medium/Low confidence that describes
data quality only -- it never overrides the rule outcome.

Rule types (all fields in the scheme payload):
  record    requirement is satisfied (verified or supplied by the citizen)
  minValue  canonical ``field`` of ``requirement`` >= ``value``
  maxValue  canonical ``field`` of ``requirement`` <= ``value``
  equals    canonical ``field`` equals ``value`` (case-insensitive)
  oneOf     canonical ``field`` is one of ``values``
  noneOf    canonical ``field`` is none of ``values`` (e.g. existing benefits)
  age       citizen age from the identity record within ``min``..``max``
"""
from __future__ import annotations

from datetime import date
from typing import Optional

SUCCESS_STATUSES = frozenset({"VALIDATED", "RETRIEVED"})
ELIGIBLE, NOT_ELIGIBLE, CANNOT_CONFIRM, NOT_ASSESSED = "ELIGIBLE", "NOT_ELIGIBLE", "CANNOT_CONFIRM", "NOT_ASSESSED"
PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"

_REASONS = {
    "missing": ("This information has not been provided yet.", "ही माहिती अद्याप दिलेली नाही."),
    "pending": ("This information is still being verified.", "ही माहिती अद्याप पडताळली जात आहे."),
    "unverified": ("A document was provided; its details still need to be verified.", "दस्तऐवज दिला आहे; त्यातील तपशील अद्याप पडताळायचे आहेत."),
    "rejected": ("The information could not be verified.", "माहिती पडताळता आली नाही."),
    "expired": ("The verified record has expired.", "पडताळलेल्या नोंदीची मुदत संपली आहे."),
    "no_value": ("The verified record does not include this detail.", "पडताळलेल्या नोंदीत हा तपशील नाही."),
    "no_dob": ("Your date of birth is not available.", "आपली जन्मतारीख उपलब्ध नाही."),
    "provided": ("Provided by you.", "आपण दिले आहे."),
    "verified": ("Verified.", "पडताळले."),
}


def _reason(key: str) -> dict:
    en, mr = _REASONS[key]
    return {"reason": en, "reasonMr": mr}


def _age_on(dob: str, today: date) -> Optional[int]:
    try:
        born = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source(requirement: dict) -> str:
    """Where a satisfied requirement's data came from: a provider-verified
    record, or a document the citizen uploaded themselves."""
    return "MANUAL" if requirement.get("documentId") else "VERIFIED"


def _evaluate_rule(rule: dict, requirements: dict, profile: dict, today: date) -> dict:
    kind = rule.get("type")
    result = {"id": rule.get("id"), "type": kind, "label": rule.get("label"), "labelMr": rule.get("labelMr") or rule.get("label"),
              "requirementCode": rule.get("requirement")}

    if kind == "age":
        age = _age_on(profile.get("dob") or "", today) if profile.get("dob") else None
        if age is None:
            return {**result, "status": UNKNOWN, "source": "PROFILE", **_reason("no_dob")}
        low, high = rule.get("min"), rule.get("max")
        ok = (low is None or age >= low) and (high is None or age <= high)
        return {**result, "status": PASS if ok else FAIL, "source": "PROFILE", "observed": age,
                "reason": f"Age {age}.", "reasonMr": f"वय {age}."}

    requirement = requirements.get(rule.get("requirement"))
    status = (requirement or {}).get("status")
    if requirement is None or status in (None, "NOT_PROVIDED"):
        return {**result, "status": UNKNOWN, "source": None, **_reason("missing")}
    if status in {"WAITING", "PROCESSING"}:
        return {**result, "status": UNKNOWN, "source": None, **_reason("pending")}
    if status not in SUCCESS_STATUSES:
        reasons = " ".join((requirement.get("validation") or {}).get("reasons") or [])
        return {**result, "status": UNKNOWN, "source": None, **_reason("expired" if "expired" in reasons.lower() else "rejected")}

    source = _source(requirement)
    if kind == "record":
        return {**result, "status": PASS, "source": source, **_reason("provided" if source == "MANUAL" else "verified")}

    if source == "MANUAL":
        # An uploaded document is accepted as provided, but its values are not
        # machine-verified -- a value rule can never pass or fail on it.
        return {**result, "status": UNKNOWN, "source": source, **_reason("unverified")}
    observed = (requirement.get("canonical") or {}).get(rule.get("field"))
    if observed is None:
        return {**result, "status": UNKNOWN, "source": source, **_reason("no_value")}

    if kind in {"minValue", "maxValue"}:
        number, limit = _number(observed), _number(rule.get("value"))
        if number is None or limit is None:
            return {**result, "status": UNKNOWN, "source": source, **_reason("no_value")}
        ok = number >= limit if kind == "minValue" else number <= limit
    elif kind == "equals":
        ok = str(observed).strip().lower() == str(rule.get("value")).strip().lower()
    elif kind in {"oneOf", "noneOf"}:
        allowed = {str(value).strip().lower() for value in rule.get("values") or []}
        ok = (str(observed).strip().lower() in allowed) == (kind == "oneOf")
    else:
        return {**result, "status": UNKNOWN, "source": source, "reason": "Unsupported rule.", "reasonMr": "असमर्थित नियम."}
    display = observed if not isinstance(observed, float) else round(observed, 2)
    return {**result, "status": PASS if ok else FAIL, "source": source, "observed": display,
            "reason": f"Verified value: {display}.", "reasonMr": f"पडताळलेले मूल्य: {display}."}


def _open_conflicts(application: dict) -> bool:
    for key in ("conflicts", "conflictReviews", "entityReviews"):
        for item in application.get(key) or []:
            if str(item.get("status", "")).upper() not in {"RESOLVED", "APPROVED", "REJECTED", "CLOSED", "COMPLETED"}:
                return True
    return False


def evaluate_eligibility(rules: list[dict], application: dict, profile: Optional[dict] = None, today: Optional[date] = None) -> dict:
    """Pure evaluation -- no I/O. ``profile`` carries the citizen's identity
    fields (at least ``dob``)."""
    today = today or date.today()
    if not rules:
        return {"result": NOT_ASSESSED, "criteria": [], "failedCriteria": [], "unknownCriteria": [], "conflict": False}
    requirements = {item.get("code"): item for item in application.get("requirements") or []}
    criteria = [_evaluate_rule(rule, requirements, profile or {}, today) for rule in rules]
    failed = [item for item in criteria if item["status"] == FAIL]
    unknown = [item for item in criteria if item["status"] == UNKNOWN]
    conflict = _open_conflicts(application)
    if failed:
        result = NOT_ELIGIBLE
    elif unknown or conflict:
        result = CANNOT_CONFIRM
    else:
        result = ELIGIBLE
    return {"result": result, "criteria": criteria, "failedCriteria": [item["id"] for item in failed],
            "unknownCriteria": [item["id"] for item in unknown], "conflict": conflict}


def data_quality(assessment: dict, application: dict) -> dict:
    """Admin-only: requirement completeness plus a data-quality confidence.
    HIGH   every criterion decided on provider-verified or identity data;
    MEDIUM decided, but at least one criterion relied on a citizen upload;
    LOW    some criterion could not be decided (missing/unverified/conflict)."""
    counts = {"total": 0, "verifiedByProvider": 0, "providedByCitizen": 0, "pending": 0, "notProvided": 0, "failed": 0}
    for requirement in application.get("requirements") or []:
        counts["total"] += 1
        status = requirement.get("status")
        if status in SUCCESS_STATUSES:
            counts["providedByCitizen" if requirement.get("documentId") else "verifiedByProvider"] += 1
        elif status in {"WAITING", "PROCESSING"}:
            counts["pending"] += 1
        elif status in (None, "NOT_PROVIDED"):
            counts["notProvided"] += 1
        else:
            counts["failed"] += 1
    decided = [item for item in assessment["criteria"] if item["status"] != UNKNOWN]
    if assessment["result"] == NOT_ASSESSED:
        confidence, why = None, "No eligibility rules are configured for this scheme."
    elif assessment["unknownCriteria"] or assessment["conflict"]:
        confidence, why = "LOW", "Some criteria could not be evaluated from verified data."
    elif any(item.get("source") == "MANUAL" for item in decided):
        confidence, why = "MEDIUM", "At least one criterion relies on a citizen-supplied document."
    else:
        confidence, why = "HIGH", "Every criterion was decided on provider-verified or identity data."
    return {"completeness": counts, "confidence": confidence, "confidenceReason": why}


def citizen_view(assessment: dict) -> dict:
    """What a citizen may see: outcome and per-criterion result/reason.
    Rule internals (fields, sources) are never exposed."""
    return {
        "result": assessment["result"],
        "conflict": assessment["conflict"],
        "criteria": [{key: item.get(key) for key in ("id", "label", "labelMr", "status", "reason", "reasonMr")} for item in assessment["criteria"]],
    }


def _scheme_rules(service_id: Optional[str]) -> list[dict]:
    if not service_id:
        return []
    from sqlalchemy.orm import Session
    from app.core.persistence import SchemeCatalogRow, engine
    with Session(engine) as session:
        row = session.get(SchemeCatalogRow, service_id)
        return list((row.payload or {}).get("eligibilityRules") or []) if row else []


def citizen_profile(citizen_id: Optional[str]) -> dict:
    """The citizen's identity record (platform citizen master first, then the
    account profile) -- the only non-requirement input to eligibility."""
    if not citizen_id:
        return {}
    from sqlalchemy.orm import Session
    from app.core.persistence import CitizenRow, UserAccountRow, engine
    with Session(engine) as session:
        citizen = session.get(CitizenRow, citizen_id)
        if citizen:
            return {"dob": citizen.date_of_birth, "district": citizen.district}
        account = session.get(UserAccountRow, citizen_id)
        return {"dob": (account.payload or {}).get("dob"), "district": (account.payload or {}).get("district")} if account else {}


def assess_application(application: dict, cache: Optional[dict] = None) -> dict:
    """Load the scheme's rules and the citizen's identity record, then evaluate.

    ``cache`` (optional, per request) lets a caller assessing several
    applications -- e.g. a citizen's application list -- read each scheme's
    rules and the citizen's profile once instead of once per application."""
    cache = {} if cache is None else cache
    rules_key, profile_key = ("rules", application.get("serviceId")), ("profile", application.get("citizenId"))
    if rules_key not in cache:
        cache[rules_key] = _scheme_rules(application.get("serviceId"))
    if profile_key not in cache:
        cache[profile_key] = citizen_profile(application.get("citizenId"))
    return evaluate_eligibility(cache[rules_key], application, cache[profile_key])
