"""Admin Provider / Integration Registry: a full operational view built
entirely on the existing capability catalog (provider_capability_snapshot/
dependency_registry), the existing health detector (integration_health),
the existing provider incident model (provider_incidents_summary), and the
existing schema mapping table -- no second provider-selection engine, no
fabricated data.
"""
from __future__ import annotations

import unittest
from fastapi import HTTPException

from app.api.admin_routes import provider_registry, provider_registry_detail_route
from app.core.auth import require_roles
from app.core.persistence import initialize


class ProviderRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_registry_role_enforced(self):
        guard = require_roles("ADMIN")
        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "CITIZEN_001", "role": "CITIZEN"})
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "OFFICER_MH_01", "role": "OFFICER"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_registry_lists_every_active_provider_with_real_fields(self):
        admin = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = provider_registry(admin)
        self.assertIn("providers", res)
        self.assertIsInstance(res["providers"], list)
        self.assertGreater(len(res["providers"]), 0, "the seeded demo catalog must have at least one active provider")

        for item in res["providers"]:
            for field in ("providerId", "name", "department", "adapterType", "environment", "authType",
                          "active", "health", "capabilities", "supportedRequirements", "successCount", "failureCount"):
                self.assertIn(field, item)
            self.assertIn("status", item["health"])
            self.assertIsInstance(item["capabilities"], list)
            self.assertIsInstance(item["supportedRequirements"], list)
            # No provider is ever selectable without at least one capability
            # in the real catalog -- registry must not fabricate a provider
            # that has none.
            for capability in item["capabilities"]:
                self.assertIn("requirementCode", capability)
                self.assertIn("priority", capability)

    def test_registry_matches_the_real_capability_catalog_no_second_selection_engine(self):
        """The registry's supportedRequirements for each provider must equal
        exactly what the existing dependency_registry/select_dependency_provider
        machinery would offer -- proving the registry reads the same data,
        not a hardcoded or duplicated mapping."""
        from app.engine.adapters import integration_health
        from app.engine.registry import dependency_registry
        admin = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = provider_registry(admin)
        real_registry = dependency_registry(integration_health())
        real_by_provider: dict[str, set[str]] = {}
        for entry in real_registry:
            real_by_provider.setdefault(entry["providerId"], set()).add(entry["requirementCode"])

        for item in res["providers"]:
            expected = real_by_provider.get(item["providerId"], set())
            self.assertEqual(set(item["supportedRequirements"]), expected)

    def test_provider_detail_returns_capabilities_schema_mappings_and_reliability(self):
        admin = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        registry = provider_registry(admin)["providers"]
        self.assertTrue(registry)
        provider_id = registry[0]["providerId"]

        detail = provider_registry_detail_route(provider_id, user=admin)
        for field in ("providerId", "name", "department", "adapterType", "health", "capabilities",
                      "schemaMappings", "reliability", "incidents", "auditEvents"):
            self.assertIn(field, detail)
        self.assertIn("successCount", detail["reliability"])
        self.assertIn("failureCount", detail["reliability"])
        self.assertIn("recentJobs", detail["reliability"])
        self.assertIsInstance(detail["incidents"], list)
        self.assertIsInstance(detail["auditEvents"], list)

    def test_provider_detail_404_for_unknown_provider(self):
        admin = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        with self.assertRaises(HTTPException) as ctx:
            provider_registry_detail_route("NONEXISTENT-PROVIDER-99999", user=admin)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_provider_detail_active_incident_reflects_real_health_transition(self):
        """A provider that goes DOWN must show up with an OPEN incident in
        its own detail view, and RESOLVED once it recovers -- proving the
        detail view reads the real, existing incident model rather than a
        static/fabricated snapshot."""
        from app.core.persistence import record_provider_health_transition
        admin = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        registry = provider_registry(admin)["providers"]
        provider = registry[0]
        provider_id, provider_name = provider["providerId"], provider["name"]

        from tests.incident_cleanup import now, purge_incidents_since
        self.addCleanup(purge_incidents_since, provider_name, now())
        record_provider_health_transition(provider_name, provider_name, None, "AVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")
        try:
            detail = provider_registry_detail_route(provider_id, user=admin)
            open_incidents = [i for i in detail["incidents"] if i["status"] == "OPEN"]
            self.assertTrue(open_incidents, "provider detail must surface its own open incident")
            registry_after = provider_registry(admin)["providers"]
            entry = next(p for p in registry_after if p["providerId"] == provider_id)
            self.assertIsNotNone(entry["activeIncident"])
        finally:
            record_provider_health_transition(provider_name, provider_name, None, "UNAVAILABLE", "AVAILABLE", None)

        detail_after = provider_registry_detail_route(provider_id, user=admin)
        self.assertFalse([i for i in detail_after["incidents"] if i["status"] == "OPEN"])


if __name__ == "__main__":
    unittest.main()
