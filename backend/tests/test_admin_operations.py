from __future__ import annotations

import unittest
from fastapi import HTTPException

from app.api.admin_routes import router, operations_overview, list_admin_applications, get_admin_application_detail
from app.core.auth import require_roles
from app.core.persistence import (
    Session, engine, ApplicationRow, initialize, create_application,
)


class AdminOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_admin_role_enforced_on_all_new_operations_routes(self):
        guard = require_roles("ADMIN")
        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "CITIZEN_001", "role": "CITIZEN"})
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            guard({"userId": "OFFICER_MH_01", "role": "OFFICER"})
        self.assertEqual(ctx.exception.status_code, 403)

        admin = guard({"userId": "ADMIN_MH_01", "role": "ADMIN"})
        self.assertEqual(admin["role"], "ADMIN")

    def test_operations_overview_returns_expected_structure(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        overview = operations_overview(admin_user)
        
        self.assertIn("system", overview)
        self.assertIn("postgres", overview["system"])
        self.assertTrue(overview["system"]["zeroDocumentCentralization"])
        self.assertIn("auditChainValid", overview["system"])
        
        self.assertIn("applications", overview)
        self.assertIn("total", overview["applications"])
        self.assertIn("automaticallyVerified", overview["applications"])
        self.assertIn("requiringAttention", overview["applications"])
        
        self.assertIn("providers", overview)
        self.assertIn("total", overview["providers"])
        self.assertIn("available", overview["providers"])
        
        self.assertIn("jobs", overview)
        self.assertIn("counts", overview["jobs"])
        
        self.assertIn("exceptions", overview)
        self.assertIn("totalAlerts", overview["exceptions"])

    def test_list_admin_applications_with_filters(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = list_admin_applications(status=None, search=None, limit=10, user=admin_user)
        self.assertIn("applications", res)
        self.assertIsInstance(res["applications"], list)

        if res["applications"]:
            first = res["applications"][0]
            self.assertIn("appId", first)
            self.assertIn("citizenId", first)
            self.assertIn("status", first)
            self.assertIn("requirementsCount", first)
            self.assertIn("fulfilledCount", first)

            # Test filter by exact appId
            search_res = list_admin_applications(status=None, search=first["appId"], limit=5, user=admin_user)
            self.assertTrue(any(a["appId"] == first["appId"] for a in search_res["applications"]))

    def test_get_admin_application_detail(self):
        admin_user = {"userId": "ADMIN_MH_01", "role": "ADMIN"}
        res = list_admin_applications(status=None, search=None, limit=1, user=admin_user)
        if res["applications"]:
            app_id = res["applications"][0]["appId"]
            detail = get_admin_application_detail(app_id, user=admin_user)
            self.assertEqual(detail["appId"], app_id)
            self.assertIn("requirements", detail)
            self.assertIn("dependencies", detail)
            self.assertIn("jobs", detail)
            self.assertIn("auditEntries", detail)

            for req in detail["requirements"]:
                self.assertIn("fulfillmentMethod", req)
                self.assertIn("sourceCandidates", req)

        with self.assertRaises(HTTPException) as ctx:
            get_admin_application_detail("NONEXISTENT-APP-99999", user=admin_user)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
