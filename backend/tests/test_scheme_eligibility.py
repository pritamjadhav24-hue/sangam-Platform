"""Deterministic scheme eligibility (app.engine.eligibility): rule outcomes,
the never-ineligible-on-missing-data guarantee, admin data quality, and the
citizen-safe projection."""
from __future__ import annotations

import unittest
from datetime import date

from app.engine.eligibility import (
    CANNOT_CONFIRM, ELIGIBLE, NOT_ELIGIBLE, citizen_view, data_quality, evaluate_eligibility,
)
from app.engine.registry import ELIGIBILITY_RULES, SCHEMES

RULES = ELIGIBILITY_RULES["SCH-MH-2026"]
TODAY = date(2026, 9, 25)


def _req(code, status="RETRIEVED", canonical=None, **extra):
    return {"code": code, "status": status, "canonical": canonical or {}, **extra}


def _scholarship(income=450000, marks=72.0, state="Maharashtra", bank="VERIFIED", **overrides):
    requirements = {
        "IDENTITY": _req("IDENTITY", canonical={"identityStatus": "VERIFIED"}),
        "INCOME_PROOF": _req("INCOME_PROOF", "VALIDATED", {"incomeAmount": income}),
        "CASTE_PROOF": _req("CASTE_PROOF", "VALIDATED", {"category": "OTHER_BACKWARD_CLASSES"}),
        "DOMICILE_PROOF": _req("DOMICILE_PROOF", "VALIDATED", {"state": state}),
        "ACADEMIC_RECORD": _req("ACADEMIC_RECORD", canonical={"percentage": marks}),
        "BANK_DETAILS": _req("BANK_DETAILS", canonical={"bankStatus": bank}),
    }
    requirements.update(overrides)
    return {"appId": "APP-T", "serviceId": "SCH-MH-2026", "requirements": list(requirements.values())}


class EligibilityOutcomeTests(unittest.TestCase):
    def test_eligible_citizen(self):
        result = evaluate_eligibility(RULES, _scholarship(), {"dob": "2005-06-15"}, TODAY)
        self.assertEqual(result["result"], ELIGIBLE)
        self.assertEqual(result["failedCriteria"], [])
        self.assertTrue(all(item["status"] == "PASS" for item in result["criteria"]))

    def test_ineligible_citizen_names_the_failed_rule(self):
        result = evaluate_eligibility(RULES, _scholarship(income=750000), {}, TODAY)
        self.assertEqual(result["result"], NOT_ELIGIBLE)
        self.assertEqual(result["failedCriteria"], ["family_income_limit"])
        failed = next(item for item in result["criteria"] if item["id"] == "family_income_limit")
        self.assertEqual(failed["observed"], 750000)
        self.assertIn("750000", failed["reason"])

    def test_missing_data_is_never_ineligible(self):
        app = _scholarship(INCOME_PROOF=_req("INCOME_PROOF", "NOT_PROVIDED"), ACADEMIC_RECORD=_req("ACADEMIC_RECORD", "WAITING"))
        result = evaluate_eligibility(RULES, app, {}, TODAY)
        self.assertEqual(result["result"], CANNOT_CONFIRM)
        self.assertEqual(set(result["unknownCriteria"]), {"family_income_limit", "qualifying_marks"})
        self.assertEqual(result["failedCriteria"], [])

    def test_a_verified_failure_outweighs_missing_data(self):
        app = _scholarship(marks=41.0, INCOME_PROOF=_req("INCOME_PROOF", "NOT_PROVIDED"))
        self.assertEqual(evaluate_eligibility(RULES, app, {}, TODAY)["result"], NOT_ELIGIBLE)

    def test_manually_uploaded_values_are_not_machine_verified(self):
        app = _scholarship(INCOME_PROOF=_req("INCOME_PROOF", "VALIDATED", {"title": "My income certificate"}, documentId="DOC-1"))
        result = evaluate_eligibility(RULES, app, {}, TODAY)
        self.assertEqual(result["result"], CANNOT_CONFIRM)
        income = next(item for item in result["criteria"] if item["id"] == "family_income_limit")
        self.assertEqual((income["status"], income["source"]), ("UNKNOWN", "MANUAL"))

    def test_expired_record_is_unknown_with_a_clear_reason(self):
        app = _scholarship(DOMICILE_PROOF=_req("DOMICILE_PROOF", "REJECTED", validation={"valid": False, "reasons": ["Source credential expired"]}))
        domicile = next(item for item in evaluate_eligibility(RULES, app, {}, TODAY)["criteria"] if item["id"] == "maharashtra_domicile")
        self.assertEqual(domicile["status"], "UNKNOWN")
        self.assertIn("expired", domicile["reason"])

    def test_open_conflict_prevents_confirmation(self):
        app = {**_scholarship(), "conflicts": [{"status": "DETECTED", "canonicalField": "incomeAmount"}]}
        result = evaluate_eligibility(RULES, app, {}, TODAY)
        self.assertEqual(result["result"], CANNOT_CONFIRM)
        self.assertTrue(result["conflict"])

    def test_age_category_and_existing_benefit_rules(self):
        rules = [
            {"id": "adult", "type": "age", "min": 18, "max": 60},
            {"id": "category", "type": "oneOf", "requirement": "CASTE_PROOF", "field": "category", "values": ["SC", "ST", "OTHER_BACKWARD_CLASSES"]},
            {"id": "not_already_enrolled", "type": "noneOf", "requirement": "SCHEME_ENROLLMENT_STATUS", "field": "welfareSchemeName", "values": ["PM-KISAN"]},
        ]
        app = {"requirements": [_req("CASTE_PROOF", "VALIDATED", {"category": "OPEN"}), _req("SCHEME_ENROLLMENT_STATUS", canonical={"welfareSchemeName": "PM-KISAN"})]}
        result = evaluate_eligibility(rules, app, {"dob": "2010-01-01"}, TODAY)
        self.assertEqual(result["failedCriteria"], ["adult", "category", "not_already_enrolled"])
        self.assertEqual(evaluate_eligibility(rules[:1], {"requirements": []}, {}, TODAY)["result"], CANNOT_CONFIRM, "no date of birth -> unknown, not ineligible")


class DataQualityTests(unittest.TestCase):
    def test_confidence_reflects_data_quality_not_outcome(self):
        eligible = evaluate_eligibility(RULES, _scholarship(), {}, TODAY)
        self.assertEqual(data_quality(eligible, _scholarship())["confidence"], "HIGH")
        manual_identity = _scholarship(IDENTITY=_req("IDENTITY", "VALIDATED", documentId="DOC-ID"))
        self.assertEqual(data_quality(evaluate_eligibility(RULES, manual_identity, {}, TODAY), manual_identity)["confidence"], "MEDIUM")
        missing = _scholarship(INCOME_PROOF=_req("INCOME_PROOF", "NOT_PROVIDED"))
        quality = data_quality(evaluate_eligibility(RULES, missing, {}, TODAY), missing)
        self.assertEqual(quality["confidence"], "LOW")
        self.assertEqual(quality["completeness"]["notProvided"], 1)
        self.assertEqual(quality["completeness"]["verifiedByProvider"], 5)


class CitizenProjectionAndCatalogTests(unittest.TestCase):
    def test_citizen_view_hides_rule_internals(self):
        view = citizen_view(evaluate_eligibility(RULES, _scholarship(income=750000), {}, TODAY))
        self.assertEqual(view["result"], NOT_ELIGIBLE)
        for item in view["criteria"]:
            self.assertEqual(set(item), {"id", "label", "labelMr", "status", "reason", "reasonMr"})

    def test_every_rule_reads_a_requirement_its_scheme_collects(self):
        for scheme in SCHEMES:
            collected = {item["code"] for item in scheme["requirements"]}
            self.assertTrue(scheme["eligibilityRules"], scheme["id"])
            for rule in scheme["eligibilityRules"]:
                if rule["type"] != "age":
                    self.assertIn(rule["requirement"], collected, f"{scheme['id']}:{rule['id']}")

    def test_application_response_carries_the_assessment(self):
        from app.api.citizen_routes import _safe_application
        safe = _safe_application({"appId": "APP-X", "serviceId": "NO-SUCH-SCHEME", "status": "IN_PROGRESS", "requirements": []})
        self.assertEqual(safe["eligibilityAssessment"]["result"], "NOT_ASSESSED")


if __name__ == "__main__":
    unittest.main()
