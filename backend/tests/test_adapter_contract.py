import os
import unittest

from app.core.provider_config import provider_runtime_config
from app.engine.adapters import AdapterFactory, AdapterResult, RestAPIAdapter


class AdapterContractTests(unittest.TestCase):
    def test_mock_adapter_implements_generic_operations_and_metadata(self):
        adapter = RestAPIAdapter("Sandbox Provider", lambda citizen_id: {"recordId": f"R-{citizen_id}"})
        self.assertEqual(adapter.health_check("CORR-1")["correlationId"], "CORR-1")
        result = adapter.retrieve("CITIZEN_001", correlation_id="APP-1", idempotency_key="DEP-1")
        self.assertIsInstance(result, AdapterResult)
        self.assertEqual(result.record["recordId"], "R-CITIZEN_001")
        self.assertEqual(result.correlation_id, "APP-1")
        self.assertEqual(result.idempotency_key, "DEP-1")

    def test_timeout_is_bounded_and_classified_without_secret_exposure(self):
        adapter = RestAPIAdapter("Sandbox Provider", lambda _: (_ for _ in ()).throw(TimeoutError("sandbox timeout")))
        result = adapter.fetch("CITIZEN_001", simulate_timeout=True)
        self.assertTrue(result["queued"])
        self.assertEqual(result["attempts"], 3)
        os.environ["PROVIDER_SANDBOX_PROVIDER_CLIENT_SECRET"] = "test-only-secret"
        safe = provider_runtime_config("Sandbox Provider")
        self.assertNotIn("test-only-secret", str(safe))
        self.assertTrue(safe["clientSecretConfigured"])
        os.environ.pop("PROVIDER_SANDBOX_PROVIDER_CLIENT_SECRET", None)

    def test_two_providers_use_same_adapter_type_without_provider_mapping(self):
        first = AdapterFactory.create("REST API", "Provider A", "academic_fetch")
        second = AdapterFactory.create("REST API", "Provider B", "academic_fetch")
        self.assertIsInstance(first, RestAPIAdapter)
        self.assertIsInstance(second, RestAPIAdapter)
        self.assertEqual(first.kind, second.kind)


if __name__ == "__main__":
    unittest.main()
