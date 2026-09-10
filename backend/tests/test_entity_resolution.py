import unittest

from app.core.demo_state import reset_demo_state
from app.core.persistence import hydrate_state, persist_state
from app.engine.entity_resolution import resolve
from app.engine.validation_engine import detect_canonical_conflicts
from app.engine.workflow_engine import APPLICATIONS, ENTITY_REVIEWS


BASE = {"citizenId": "CITIZEN_001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91 9876543210"}


class EntityResolutionTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_exact_and_normalized_matches_are_high(self):
        exact = resolve(BASE, {**BASE, "recordId": "R1", "sourceSystem": "Revenue Department"})
        formatted = resolve(BASE, {"recordId": "R2", "name": "RAHUL-KUMAR", "dob": "15/06/2005", "phone": "9876543210", "sourceSystem": "Education Department"})
        self.assertEqual(exact["confidenceLevel"], "HIGH")
        self.assertEqual(formatted["confidenceLevel"], "HIGH")
        self.assertEqual(formatted["decision"], "AUTO_ACCEPT")
        self.assertTrue(any(item["field"] == "date_of_birth" and item["normalizedMatch"] for item in formatted["fieldComparisons"]))

    def test_partial_name_is_medium_and_low_candidate_is_unresolved(self):
        medium = resolve(BASE, {"recordId": "R3", "name": "Rahul", "dob": "2005-06-15", "sourceSystem": "Education Department"})
        low = resolve(BASE, {"recordId": "R4", "name": "Rahul Kumar", "dob": "2004-01-01", "phone": "+91 9000000000", "sourceSystem": "Revenue Department"})
        self.assertEqual(medium["confidenceLevel"], "MEDIUM")
        self.assertEqual(medium["decision"], "REVIEW")
        self.assertEqual(low["confidenceLevel"], "LOW")
        self.assertEqual(low["decision"], "UNRESOLVED")

    def test_different_citizens_with_similar_names_do_not_link(self):
        result = resolve(BASE, {"recordId": "R5", "name": "Rahul Kumar", "dob": "2004-01-01", "phone": "+91 9000000002", "sourceSystem": "Education Department"})
        self.assertEqual(result["decision"], "UNRESOLVED")
        self.assertIn("date_of_birth", [item["field"] for item in result["fieldComparisons"]])

    def test_income_difference_is_conflict_not_identity_mismatch(self):
        result = resolve(BASE, {"recordId": "R6", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91 9876543210", "annual_income": "180000", "sourceSystem": "Revenue Department"})
        self.assertEqual(result["decision"], "AUTO_ACCEPT")
        conflict = detect_canonical_conflicts([
            {"sourceSystem": "Revenue Department", "sourceRecordId": "R6", "record": {"annual_income": "180000"}},
            {"sourceSystem": "Education Department", "sourceRecordId": "E6", "record": {"familyAnnualIncome": "240000"}},
        ])
        self.assertEqual(conflict[0]["canonicalField"], "incomeAmount")

    def test_provenance_and_field_explanations_are_retained(self):
        result = resolve(BASE, {"recordId": "R7", "name": "Rahul K", "dob": "2005/06/15", "phone": "+919876543210", "sourceSystem": "Education Department"})
        self.assertEqual(result["provenance"]["sourceSystem"], "Education Department")
        self.assertEqual(result["candidateRecordId"], "R7")
        self.assertTrue(result["fieldComparisons"])
        self.assertTrue(result["weights"])

    def test_review_metadata_survives_postgres_roundtrip(self):
        app_id = "SCH-MH-ENTITY-001"
        review_id = "ER-SCH-MH-ENTITY-001-001"
        review = {"reviewId": review_id, "appId": app_id, "status": "WAITING_FOR_OFFICER", "decision": None, "confidenceScore": 0.78, "fieldComparisons": [{"field": "name", "score": 0.7}], "provenance": {"sourceSystem": "Education Department", "sourceRecordId": "E1"}}
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN_001", "status": "WAITING_FOR_OFFICER", "statusHistory": [], "requirements": [], "dependencyIds": [], "entityReviews": [review], "conflictReviews": [], "eligibility": {}}
        ENTITY_REVIEWS[review_id] = review
        persist_state(); APPLICATIONS.clear(); ENTITY_REVIEWS.clear(); hydrate_state()
        self.assertEqual(ENTITY_REVIEWS[review_id]["provenance"]["sourceSystem"], "Education Department")
        self.assertEqual(ENTITY_REVIEWS[review_id]["fieldComparisons"][0]["score"], 0.7)


if __name__ == "__main__":
    unittest.main()
