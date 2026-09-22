"""Phase 5: failure classification and provider-fallback decision logic
(app.engine.retry_policy). Pure unit tests -- no live server needed; provider
candidates are supplied via the same provider_capability_snapshot mocking
technique already established in Phases 3/4.
"""
import unittest
from unittest.mock import patch

from app.engine.retry_policy import (
    FALLBACK_PROVIDER, NONE_OUTCOME, NOT_RETRYABLE, RETRY_SAME_PROVIDER, WAITING_RETRY_EXHAUSTED,
    find_fallback_candidate, is_retryable_category, retry_decision,
)


class FailureClassificationTests(unittest.TestCase):
    """Requirements 1-3: retryable categories; 4-5 (non-retryable) below."""

    def test_timeout_is_retryable(self):
        self.assertTrue(is_retryable_category("TIMEOUT"))

    def test_network_failure_is_retryable(self):
        self.assertTrue(is_retryable_category("NETWORK_ERROR"))

    def test_transient_upstream_failure_is_retryable(self):
        self.assertTrue(is_retryable_category("UPSTREAM_ERROR"))
        self.assertTrue(is_retryable_category("UPSTREAM_UNAVAILABLE"))
        self.assertTrue(is_retryable_category("RATE_LIMITED"))

    def test_validation_failure_is_not_retryable(self):
        self.assertFalse(is_retryable_category("VALIDATION_ERROR"))

    def test_auth_failures_are_not_retryable(self):
        self.assertFalse(is_retryable_category("AUTHENTICATION_ERROR"))
        self.assertFalse(is_retryable_category("AUTHORIZATION_ERROR"))

    def test_unsupported_and_malformed_are_not_retryable(self):
        self.assertFalse(is_retryable_category("UNSUPPORTED_OPERATION"))
        self.assertFalse(is_retryable_category("MALFORMED_RESPONSE"))
        self.assertFalse(is_retryable_category("SCHEMA_MISMATCH"))

    def test_unknown_category_defaults_to_not_retryable(self):
        self.assertFalse(is_retryable_category(None))
        self.assertFalse(is_retryable_category("SOMETHING_NEW"))


class RetryDecisionTests(unittest.TestCase):
    def test_completed_dependency_has_no_retry_decision(self):
        self.assertEqual(retry_decision({"status": "COMPLETED"}), NONE_OUTCOME)

    def test_no_error_yet_has_no_retry_decision(self):
        self.assertEqual(retry_decision({"status": "WAITING_FOR_DEPENDENCY", "attempts": 0, "maxAttempts": 3}), NONE_OUTCOME)

    def test_invalid_consent_is_never_a_retry_decision_input(self):
        """Consent failures raise ConsentAuthorizationError before a
        dependency ever records an errorCategory -- there is nothing for
        retry_decision to retry, matching 'invalid consent is not retried'."""
        dep = {"status": "WAITING_FOR_DEPENDENCY", "attempts": 0, "maxAttempts": 3, "errorCategory": None}
        self.assertEqual(retry_decision(dep), NONE_OUTCOME)

    def test_non_retryable_category_is_not_retried(self):
        dep = {"status": "WAITING_FOR_DEPENDENCY", "errorCategory": "VALIDATION_ERROR", "attempts": 1, "maxAttempts": 3}
        self.assertEqual(retry_decision(dep), NOT_RETRYABLE)

    def test_retryable_category_under_attempt_limit_retries_the_same_provider(self):
        dep = {"status": "WAITING_FOR_DEPENDENCY", "errorCategory": "NETWORK_ERROR", "attempts": 1, "maxAttempts": 3}
        self.assertEqual(retry_decision(dep), RETRY_SAME_PROVIDER)

    def test_retries_increment_and_eventually_exhaust_without_a_fallback(self):
        for attempts in (1, 2):
            dep = {"status": "WAITING_FOR_DEPENDENCY", "errorCategory": "TIMEOUT", "attempts": attempts, "maxAttempts": 3}
            self.assertEqual(retry_decision(dep), RETRY_SAME_PROVIDER)
        exhausted = {"status": "WAITING_FOR_DEPENDENCY", "errorCategory": "TIMEOUT", "attempts": 3, "maxAttempts": 3}
        self.assertEqual(retry_decision(exhausted, has_fallback_candidate=False), WAITING_RETRY_EXHAUSTED)

    def test_exhausted_retryable_failure_with_a_fallback_candidate_falls_back(self):
        dep = {"status": "WAITING_FOR_DEPENDENCY", "errorCategory": "UPSTREAM_UNAVAILABLE", "attempts": 3, "maxAttempts": 3}
        self.assertEqual(retry_decision(dep, has_fallback_candidate=True), FALLBACK_PROVIDER)


class FallbackCandidateDiscoveryTests(unittest.TestCase):
    """Requirement 13: multiple eligible providers are handled purely from
    the existing capability registry data -- no hardcoded department names
    or fallback chains appear anywhere in this discovery path."""

    def test_finds_a_different_healthy_provider_for_the_same_requirement(self):
        candidates = [
            {"requirementCode": "PHASE5_FALLBACK", "provider": "Provider A", "providerId": "PROV-A", "requiredService": "X",
             "serviceName": "X", "serviceId": "SVC-A", "adapter": "Department Sandbox API", "priority": 10},
            {"requirementCode": "PHASE5_FALLBACK", "provider": "Provider B", "providerId": "PROV-B", "requiredService": "X",
             "serviceName": "X", "serviceId": "SVC-B", "adapter": "Department Sandbox API", "priority": 20},
        ]
        health = [{"system": "Provider A", "providerId": "PROV-A", "status": "AVAILABLE"},
                  {"system": "Provider B", "providerId": "PROV-B", "status": "AVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates), \
             patch("app.engine.adapters.integration_health", return_value=health):
            candidate = find_fallback_candidate("PHASE5_FALLBACK", current_provider_id="PROV-A")
        self.assertEqual(candidate["providerId"], "PROV-B")

    def test_unhealthy_alternate_provider_is_not_offered_as_a_fallback(self):
        candidates = [
            {"requirementCode": "PHASE5_FALLBACK_UNHEALTHY", "provider": "Provider A", "providerId": "PROV-A", "requiredService": "X",
             "serviceName": "X", "serviceId": "SVC-A", "adapter": "Department Sandbox API", "priority": 10},
            {"requirementCode": "PHASE5_FALLBACK_UNHEALTHY", "provider": "Provider B (down)", "providerId": "PROV-B-DOWN", "requiredService": "X",
             "serviceName": "X", "serviceId": "SVC-B", "adapter": "Department Sandbox API", "priority": 20},
        ]
        health = [{"system": "Provider A", "providerId": "PROV-A", "status": "AVAILABLE"},
                  {"system": "Provider B (down)", "providerId": "PROV-B-DOWN", "status": "UNAVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates), \
             patch("app.engine.adapters.integration_health", return_value=health):
            candidate = find_fallback_candidate("PHASE5_FALLBACK_UNHEALTHY", current_provider_id="PROV-A")
        self.assertIsNone(candidate)

    def test_no_fallback_when_only_the_current_provider_exists(self):
        candidates = [{"requirementCode": "PHASE5_NO_FALLBACK", "provider": "Only Provider", "providerId": "ONLY",
                       "requiredService": "X", "serviceName": "X", "serviceId": "SVC-ONLY", "adapter": "Department Sandbox API", "priority": 10}]
        health = [{"system": "Only Provider", "providerId": "ONLY", "status": "AVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates), \
             patch("app.engine.adapters.integration_health", return_value=health):
            candidate = find_fallback_candidate("PHASE5_NO_FALLBACK", current_provider_id="ONLY")
        self.assertIsNone(candidate)


if __name__ == "__main__":
    unittest.main()
