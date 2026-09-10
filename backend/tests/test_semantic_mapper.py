import unittest

from app.core.demo_state import reset_demo_state
from app.core.persistence import hydrate_state, persist_state
from app.engine import semantic_mapper


class SemanticMapperTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_deterministic_exact_mapping_and_precedence(self):
        result = semantic_mapper.hybrid_mapping("Revenue", "annual_income", "number", "annual household income")
        self.assertEqual(result["canonicalField"], "incomeAmount")
        self.assertEqual(result["mappingMode"], "DETERMINISTIC_CANONICAL_RULES")
        self.assertEqual(result["confidence"], 1.0)
        self.assertIn("alternativeSuggestion", result)

    def test_ai_high_medium_low_and_review(self):
        high = semantic_mapper.ai_suggest_mapping("Education", "annual_income", "number", "income")
        medium = semantic_mapper.ai_suggest_mapping("Education", "student_marks", "number", "")
        low = semantic_mapper.ai_suggest_mapping("Education", "random_blob", "string", "")
        self.assertEqual(high["confidenceLevel"], "HIGH")
        self.assertEqual(medium["confidenceLevel"], "MEDIUM")
        self.assertTrue(medium["humanReviewRequired"])
        self.assertEqual(low["confidenceLevel"], "LOW")
        self.assertIsNone(low["canonicalField"])
        review = semantic_mapper.create_mapping_review(medium)
        self.assertEqual(review["reviewStatus"], "WAITING_FOR_OFFICER")

    def test_officer_approval_rejection_and_citizen_forbidden(self):
        review = semantic_mapper.create_mapping_review(semantic_mapper.ai_suggest_mapping("Education", "student_marks", "number"))
        with self.assertRaises(PermissionError):
            semantic_mapper.decide_mapping_review(review["reviewId"], "APPROVE", "CITIZEN_001", "CITIZEN", "not allowed")
        approved = semantic_mapper.decide_mapping_review(review["reviewId"], "APPROVE", "OFFICER_MH_01", "OFFICER", "Approved metadata mapping")
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(approved["approvedMapping"]["mappingMode"], "HUMAN_APPROVED")
        rejected = semantic_mapper.create_mapping_review(semantic_mapper.ai_suggest_mapping("Revenue", "random_blob", "string"))
        result = semantic_mapper.decide_mapping_review(rejected["reviewId"], "REJECT", "ADMIN_MH_01", "ADMIN", "Insufficient evidence")
        self.assertEqual(result["status"], "REJECTED")

    def test_simulated_schema_examples_and_no_pii(self):
        evidence = semantic_mapper.SIMULATED_SCHEMA_EVIDENCE
        income = [item for item in evidence if item["canonicalField"] == "incomeAmount"]
        self.assertGreaterEqual(len(income), 2)
        self.assertGreaterEqual(len([item for item in income if item["mappingMode"] == "DETERMINISTIC_CANONICAL_RULES"]), 2)
        serialized = str(evidence)
        self.assertNotIn("CITIZEN_001", serialized)
        self.assertNotIn("Rahul", serialized)
        self.assertNotIn("password", serialized.lower())

    def test_mapping_review_persists_after_restart_hydration(self):
        review = semantic_mapper.create_mapping_review(semantic_mapper.ai_suggest_mapping("Education", "student_marks", "number"))
        persist_state()
        semantic_mapper.MAPPING_REVIEWS.clear()
        hydrate_state()
        self.assertEqual(semantic_mapper.MAPPING_REVIEWS[review["reviewId"]]["status"], "WAITING_FOR_OFFICER")


if __name__ == "__main__":
    unittest.main()
