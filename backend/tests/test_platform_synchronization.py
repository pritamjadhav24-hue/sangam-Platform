"""Cross-layer synchronization guarantees for the final platform state:
scheme -> requirement vocabulary -> capability -> provider -> adapter ->
department API -> canonical mapping, plus the deployment-facing safety of
the demo reset and the department sandbox bootstrap.

Every check here reads the same definitions the running system uses (the
seed catalogs, the registered department API routes, the runtime mapper) --
nothing is re-declared, so a drift between layers fails a test.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.core.persistence import (
    DEMO_RUNTIME_TABLES, DEPARTMENT_SANDBOX_PROVIDERS, IN_PROCESS_SCHEMA_MAPPINGS, REQUIREMENT_CATALOG,
)
from app.engine.registry import DEPENDENCY_SERVICES, SCHEMES


class SchemeRequirementProviderAlignmentTests(unittest.TestCase):
    def test_every_scheme_requirement_is_a_known_vocabulary_code(self):
        vocabulary = {item["code"] for item in REQUIREMENT_CATALOG}
        for scheme in SCHEMES:
            for requirement in scheme["requirements"]:
                self.assertIn(requirement["code"], vocabulary, f"{scheme['id']} uses an unknown requirement code")

    def test_every_scheme_requirement_has_at_least_one_registered_provider(self):
        served = {item["requirementCode"] for item in DEPENDENCY_SERVICES} | {item["requirementCode"] for item in DEPARTMENT_SANDBOX_PROVIDERS}
        for scheme in SCHEMES:
            for requirement in scheme["requirements"]:
                self.assertIn(requirement["code"], served, f"{requirement['code']} ({scheme['id']}) has no provider capability")

    def test_income_proof_has_a_lower_priority_alternate_provider(self):
        primary = next(item for item in DEPENDENCY_SERVICES if item["requirementCode"] == "INCOME_PROOF")
        alternates = [item for item in DEPARTMENT_SANDBOX_PROVIDERS if item["requirementCode"] == "INCOME_PROOF"]
        # Revenue's income-certificate API and Social Welfare's verified
        # household income (the authorised equivalent), in that order.
        self.assertEqual({item["providerId"] for item in alternates}, {"REVENUE-SANDBOX-INCOME", "SOCIAL-WELFARE-SANDBOX-INCOME"})
        for alternate in alternates:
            self.assertGreater(alternate["priority"], primary["priority"], "the alternate must only ever be a fallback")
        by_id = {item["providerId"]: item["priority"] for item in alternates}
        self.assertLess(by_id["REVENUE-SANDBOX-INCOME"], by_id["SOCIAL-WELFARE-SANDBOX-INCOME"])

    def test_every_sandbox_provider_path_is_served_by_the_department_api(self):
        from app.department_api.main import app
        routes = {route.path.replace("{citizen_ref}", "{citizenRef}") for route in app.routes}
        for entry in DEPARTMENT_SANDBOX_PROVIDERS:
            self.assertIn(entry["httpPath"], routes, f"{entry['providerId']} points at a path no department API serves")


class SchemaMappingTruthfulnessTests(unittest.TestCase):
    """The mappings shown to administrators must be the ones actually applied."""

    def test_in_process_mappings_match_the_runtime_mapper(self):
        from app.engine.adapters import _SANDBOX_HANDLERS, _load_sandbox_handlers
        from app.engine.semantic_mapper import map_record
        _load_sandbox_handlers()
        handler_by_service = {item["serviceId"]: (item["sandboxHandler"], item["requirementCode"]) for item in DEPENDENCY_SERVICES}
        for mapping in IN_PROCESS_SCHEMA_MAPPINGS:
            handler, requirement_code = handler_by_service[mapping["service"]]
            record = _SANDBOX_HANDLERS[handler]("CITIZEN_001")
            self.assertIsNotNone(record, mapping)
            self.assertIn(mapping["field"], record, f"{mapping['provider']} has no source field {mapping['field']}")
            self.assertIn(mapping["canonical"], map_record(requirement_code, record), f"{mapping['canonical']} is never produced")

    def test_alternate_income_provider_maps_to_the_same_canonical_field_as_the_primary(self):
        alternate = next(item for item in DEPARTMENT_SANDBOX_PROVIDERS if item["providerId"] == "REVENUE-SANDBOX-INCOME")
        primary = next(item for item in IN_PROCESS_SCHEMA_MAPPINGS if item["service"] == "REV-INCOME-102")
        self.assertIn((primary["field"], primary["canonical"]), alternate["mappings"])


class DepartmentAdapterHealthTests(unittest.TestCase):
    def _adapter(self):
        from app.engine.adapters import DepartmentSandboxAPIAdapter
        return DepartmentSandboxAPIAdapter("Revenue Sandbox", provider_id="REVENUE-SANDBOX-INCOME", config={
            "endpointRef": "DEPARTMENT_API_BASE_URL", "httpPath": "/departments/revenue/income-certificates/{citizenRef}",
        })

    def test_unconfigured_endpoint_is_reported_misconfigured_not_available(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEPARTMENT_API_BASE_URL", None)
            self.assertEqual(self._adapter().health_check()["status"], "MISCONFIGURED")

    def test_configured_endpoint_is_available(self):
        with patch.dict(os.environ, {"DEPARTMENT_API_BASE_URL": "http://127.0.0.1:9101"}):
            self.assertEqual(self._adapter().health_check()["status"], "AVAILABLE")


class DemoResetSafetyTests(unittest.TestCase):
    def test_reset_never_touches_reference_data(self):
        cleared = {model.__tablename__ for model in DEMO_RUNTIME_TABLES}
        for reference in ("user_accounts", "citizens", "scheme_catalog", "scheme_requirements", "requirements",
                          "providers", "provider_capabilities", "service_catalog", "schema_mappings", "departments"):
            self.assertNotIn(reference, cleared)
        self.assertTrue({"applications", "documents", "citizen_notifications", "provider_jobs", "provider_incidents"} <= cleared)

    def test_reset_endpoint_is_refused_in_production(self):
        from app.api.admin_routes import reset_demo
        with patch.dict(os.environ, {"SANGAM_ENV": "production"}), \
             patch("app.api.admin_routes.reset_demo_database") as wipe:
            with self.assertRaises(HTTPException) as ctx:
                reset_demo(user={"userId": "ADMIN_MH_01", "role": "ADMIN"})
        self.assertEqual(ctx.exception.status_code, 403)
        wipe.assert_not_called()


class DepartmentSandboxBootstrapTests(unittest.TestCase):
    def test_startup_seeds_sandboxes_unless_disabled(self):
        from app.department_api.main import prepare_sandbox_databases
        with patch("app.sandbox.manage.seed_all") as seed_all:
            with patch.dict(os.environ, {"DEPARTMENT_SANDBOX_AUTO_SEED": "false"}):
                prepare_sandbox_databases()
            seed_all.assert_not_called()
            with patch.dict(os.environ, {"DEPARTMENT_SANDBOX_AUTO_SEED": "true"}):
                prepare_sandbox_databases()
            seed_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()
