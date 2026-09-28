"""Phase 3: requirement -> dynamic provider discovery.

These prove discovery is driven entirely by requirement code + registered
capability/service/provider metadata + health -- never by a hardcoded
department name or a fixed provider list. Fixtures use
app.core.persistence.provider_capability_snapshot mocking, the same technique
already established in test_generic_dependency_engine.py, so no real catalog
rows need to be created for the pure-discovery-mechanics tests.
"""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.demo_state import reset_demo_state
from app.engine.registry import dependency_registry, select_dependency_provider

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class DynamicProviderDiscoveryTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def test_requirement_discovers_provider_by_capability_not_department_name(self):
        """The requirement code is the only input; nothing about 'Zeta' is
        known anywhere else in this codebase -- discovery must still resolve
        it purely from registered capability data."""
        candidates = [{
            "authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE3_TEST_REQUIREMENT", "provider": "Zeta Sandbox API", "providerId": "ZETA-SANDBOX",
            "requiredService": "Zeta Lookup", "serviceName": "Zeta Lookup", "serviceId": "ZETA-SVC-001",
            "adapter": "Department Sandbox API", "priority": 5,
        }]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            selected = select_dependency_provider("PHASE3_TEST_REQUIREMENT", [{"system": "Zeta Sandbox API", "providerId": "ZETA-SANDBOX", "status": "AVAILABLE"}])
        self.assertEqual(selected["providerId"], "ZETA-SANDBOX")
        self.assertEqual(selected["serviceId"], "ZETA-SVC-001")

    def test_multiple_providers_can_satisfy_the_same_requirement(self):
        candidates = [
            {"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE3_MULTI", "provider": "Low Priority Provider", "providerId": "LOW-PRI", "requiredService": "X", "serviceName": "X", "serviceId": "SVC-LOW", "adapter": "Department Sandbox API", "priority": 50},
            {"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE3_MULTI", "provider": "High Priority Provider", "providerId": "HIGH-PRI", "requiredService": "X", "serviceName": "X", "serviceId": "SVC-HIGH", "adapter": "Department Sandbox API", "priority": 5},
        ]
        health = [{"system": "Low Priority Provider", "providerId": "LOW-PRI", "status": "AVAILABLE"}, {"system": "High Priority Provider", "providerId": "HIGH-PRI", "status": "AVAILABLE"}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            registry = dependency_registry(health)
            selected = select_dependency_provider("PHASE3_MULTI", health)
        matching = [item for item in registry if item["requirementCode"] == "PHASE3_MULTI"]
        self.assertEqual(len(matching), 2, "expected both competing providers to be visible to discovery")
        self.assertEqual(selected["providerId"], "HIGH-PRI", "lower priority number wins")

    def test_unavailable_provider_is_excluded_from_selection(self):
        candidates = [{"authorization": {"role": "AUTHORITATIVE"}, "requirementCode": "PHASE3_UNAVAILABLE", "provider": "Down Provider", "providerId": "DOWN", "requiredService": "X", "serviceName": "X", "serviceId": "SVC-DOWN", "adapter": "Department Sandbox API", "priority": 1}]
        with patch("app.core.persistence.provider_capability_snapshot", return_value=candidates):
            selected = select_dependency_provider("PHASE3_UNAVAILABLE", [{"system": "Down Provider", "providerId": "DOWN", "status": "UNAVAILABLE"}])
        self.assertIsNone(selected)

    def test_disabled_capability_excludes_a_new_dynamic_provider(self):
        """The exact same capability-enabled filtering already proven for the
        4 legacy providers (test_generic_dependency_engine.py) must hold for
        the Phase 2 department-sandbox-backed providers too -- proving
        eligibility filtering is generic, not special-cased per provider."""
        from unittest.mock import patch as _patch
        from app.core.persistence import (
            DEPARTMENT_SANDBOX_PROVIDERS, ProviderCapabilityRow, Session, engine, seed_department_sandbox_providers,
        )
        from app.engine.adapters import request_registered_service
        from tests.catalog_fixture import restore_tables, snapshot_provider_catalog
        entry = next(item for item in DEPARTMENT_SANDBOX_PROVIDERS if item["providerId"] == "REVENUE-SANDBOX-LAND")
        snapshot = snapshot_provider_catalog()
        with _patch.dict("os.environ", {"SANGAM_SEED_DEPARTMENT_PROVIDERS": "true"}):
            seed_department_sandbox_providers()
        try:
            with Session(engine) as session:
                capability = session.query(ProviderCapabilityRow).filter_by(provider_id=entry["providerId"]).first()
                capability.enabled = False
                session.commit()
            result = request_registered_service(entry["serviceId"], "SYN-CIT-00001", requirement_code=entry["requirementCode"])
            self.assertFalse(result.success)
            self.assertEqual(result.error_category, "CONFIGURATION_ERROR")
        finally:
            # Back to exactly the prior registry: rows this test added are
            # removed and the capability it disabled is re-enabled.
            restore_tables(snapshot)

    def test_no_hardcoded_department_names_inside_selection_functions(self):
        """Discovery functions must only branch on requirement/capability data.
        Department names may appear as DEV FALLBACK constants at module scope
        (SCHEMES/DEPENDENCY_SERVICES) but never inside the selection logic itself."""
        source = (BACKEND_ROOT / "app" / "engine" / "registry.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        checked = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {"select_dependency_provider", "dependency_registry"}:
                body = ast.get_source_segment(source, node)
                checked += 1
                for literal in ("Revenue Department", "Education Department", "Social Welfare Department", "REVENUE-DEPARTMENT", "TRANSPORT-SANDBOX"):
                    self.assertNotIn(literal, body, f"{node.name} must select providers only via requirement/capability data, not by name")
        self.assertEqual(checked, 2)


if __name__ == "__main__":
    unittest.main()
