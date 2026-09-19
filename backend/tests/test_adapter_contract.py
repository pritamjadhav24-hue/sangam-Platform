import os
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.core.provider_config import provider_runtime_config
from app.engine.adapters import AdapterFactory, AdapterResult, CSVFileAdapter, LegacySOAPAdapter, ProviderRequest, RestAPIAdapter
from app.core.provider_config import validate_endpoint


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

    def test_production_endpoint_requires_https_and_rejects_private_hosts(self):
        with self.assertRaises(ValueError):
            validate_endpoint("http://localhost:8080", "PRODUCTION")
        with self.assertRaises(ValueError):
            validate_endpoint("https://127.0.0.1/provider", "PRODUCTION")
        self.assertEqual(validate_endpoint("http://localhost:8080", "SANDBOX"), "http://localhost:8080")

    def test_production_rest_without_configured_endpoint_fails_safely(self):
        adapter = RestAPIAdapter("Production Provider", provider_id="PROD-1", config={"environment": "PRODUCTION", "endpointRef": "MISSING_ENDPOINT", "authType": "NONE"})
        result = adapter.retrieve({"safe": True}, correlation_id="APP-1", idempotency_key="DEP-1")
        self.assertFalse(result.success)
        self.assertEqual(result.error_category, "CONFIGURATION_ERROR")
        self.assertEqual(result.correlation_id, "APP-1")
        self.assertEqual(result.idempotency_key, "DEP-1")

    def test_soap_and_csv_production_boundaries_fail_without_fake_success(self):
        soap = LegacySOAPAdapter("SOAP Provider", provider_id="SOAP-1", config={"environment": "PRODUCTION", "endpointRef": "SOAP_ENDPOINT", "authType": "NONE"})
        self.assertIn(soap.retrieve({}, correlation_id="APP-2").error_category, {"CONFIGURATION_ERROR", "UNSUPPORTED_OPERATION"})
        csv_adapter = CSVFileAdapter("CSV Provider", provider_id="CSV-1", config={"environment": "PRODUCTION", "endpointRef": "CSV_ENDPOINT", "authType": "NONE"})
        self.assertIn(csv_adapter.retrieve({}, correlation_id="APP-3").error_category, {"CONFIGURATION_ERROR", "UNSUPPORTED_OPERATION"})

    def test_auth_reference_metadata_never_contains_secret_value(self):
        os.environ["PROVIDER_AUTH_PROVIDER_API_KEY"] = "test-only-api-key"
        adapter = RestAPIAdapter("Auth Provider", provider_id="AUTH_PROVIDER", config={"environment": "PRODUCTION", "endpointRef": "MISSING_ENDPOINT", "authType": "API_KEY"})
        safe = adapter.health_check()
        self.assertNotIn("test-only-api-key", str(safe))
        os.environ.pop("PROVIDER_AUTH_PROVIDER_API_KEY", None)

    def test_all_adapter_types_expose_the_strict_contract(self):
        for adapter in (
            RestAPIAdapter("REST", lambda _: {"recordId": "R-1"}),
            LegacySOAPAdapter("SOAP", lambda _: {"recordId": "S-1"}),
            CSVFileAdapter("CSV", lambda _: {"recordId": "C-1"}),
        ):
            for method in ("health_check", "discover", "submit", "get_status", "retrieve", "normalize"):
                self.assertTrue(callable(getattr(adapter, method)))

    def test_rest_http_categories_are_safe_and_deterministic(self):
        os.environ["PROVIDER_HTTP_PROVIDER_BASE_URL"] = "https://provider.example.test"
        adapter = RestAPIAdapter("HTTP Provider", provider_id="HTTP_PROVIDER", config={"environment": "PRODUCTION", "endpointRef": "PROVIDER_HTTP_PROVIDER_BASE_URL", "endpointPath": "status", "authType": "NONE", "maxAttempts": 3})
        with patch("app.engine.adapters.urlopen", side_effect=HTTPError("https://provider.example.test/status", 401, "unauthorized", {}, None)):
            unauthorized = adapter.retrieve({}, correlation_id="APP-4", idempotency_key="DEP-4")
        self.assertEqual(unauthorized.error_category, "AUTHENTICATION_ERROR")
        self.assertFalse(unauthorized.retryable)
        with patch("app.engine.adapters.urlopen", side_effect=HTTPError("https://provider.example.test/status", 503, "unavailable", {}, None)):
            unavailable = adapter.retrieve({}, correlation_id="APP-5", idempotency_key="DEP-5")
        self.assertEqual(unavailable.error_category, "UPSTREAM_ERROR")
        self.assertTrue(unavailable.retryable)
        self.assertEqual(unavailable.attempts, 3)
        os.environ.pop("PROVIDER_HTTP_PROVIDER_BASE_URL", None)

    def test_csv_adapter_rejects_traversal_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            outside = Path(directory) / "outside.csv"
            outside.write_text("recordId\nR-1\n", encoding="utf-8")
            os.environ.update({"CSV_PATH": str(outside), "CSV_ROOT": str(root)})
            adapter = CSVFileAdapter("CSV", provider_id="CSV", config={"environment": "PRODUCTION", "filePathRef": "CSV_PATH", "allowedDirectoryRef": "CSV_ROOT", "authType": "NONE"})
            self.assertEqual(adapter.retrieve({}).error_category, "VALIDATION_ERROR")
            large = root / "large.csv"
            large.write_text("recordId\n" + ("x" * (5 * 1024 * 1024)) + "\n", encoding="utf-8")
            os.environ["CSV_PATH"] = str(large)
            self.assertEqual(adapter.retrieve({}).error_category, "VALIDATION_ERROR")
            for key in ("CSV_PATH", "CSV_ROOT"): os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
