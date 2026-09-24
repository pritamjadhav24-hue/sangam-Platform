"""Final Admin Portal modules: Analytics/Reports, Scheme/Requirement
Catalogue and Profile/Access. All read-only, all derived from existing
persisted state, the existing capability registry and the existing
require_roles() authorization -- verified here against that same data.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

import main
from app.api.admin_routes import (
    admin_analytics, admin_profile, admin_scheme_detail, admin_schemes, operations_overview,
)
from app.core.admin_insights import classify_application_outcome, effective_access_model
from app.core.auth import issue_token, require_roles
from app.core.persistence import ApplicationRow, SchemeCatalogRow, SchemeRequirementRow, Session, engine, initialize

ADMIN = {"userId": "ADMIN_MH_01", "name": "Platform Administrator", "role": "ADMIN"}


def _analytics(**filters):
    params = {"start": None, "end": None, "status": None, "outcome": None, "provider": None,
              "requirement": None, "incident_status": None}
    params.update(filters)
    return admin_analytics(**params, user=ADMIN)


class OutcomeClassificationTests(unittest.TestCase):
    def test_outcomes_are_requirement_derived_and_mutually_exclusive(self):
        self.assertEqual(classify_application_outcome({"status": "WAITING_FOR_OFFICER", "requirements": []}), "officerReviewRequired")
        self.assertEqual(classify_application_outcome({"status": "IN_PROGRESS", "requirements": [{"status": "ACTION_REQUIRED"}]}), "citizenActionRequired")
        self.assertEqual(classify_application_outcome({"status": "IN_PROGRESS", "requirements": [{"status": "WAITING"}]}), "retryInProgress")
        self.assertEqual(classify_application_outcome({"status": "IN_PROGRESS", "requirements": [{"status": "RETRIEVED"}]}), "automaticallyVerified")
        self.assertEqual(classify_application_outcome({"status": "IN_PROGRESS", "requirements": [{"status": "VALIDATED", "documentId": "DOC-1"}]}), "manuallyFulfilled")
        self.assertEqual(classify_application_outcome({"status": "IN_PROGRESS", "requirements": [{"status": "PENDING"}]}), "processing")


class AnalyticsTests(unittest.TestCase):
    APP_ID = "APP-ANALYTICS-TEST-001"

    @classmethod
    def setUpClass(cls):
        initialize()
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=cls.APP_ID, citizen_id="CITIZEN_ANALYTICS", status="IN_PROGRESS", payload={
                "appId": cls.APP_ID, "citizenId": "CITIZEN_ANALYTICS", "status": "IN_PROGRESS", "serviceId": "SCH-MH-2026",
                "createdAt": "2020-01-15T10:00:00+00:00",
                "requirements": [
                    {"code": "ANALYTICS_REQ_AUTO", "status": "RETRIEVED", "providerId": "REVENUE-DEPARTMENT", "isFallback": True,
                     "fallbackAttempts": [{"providerId": "EDUCATION-DEPARTMENT", "success": False}, {"providerId": "REVENUE-DEPARTMENT", "success": True}]},
                    {"code": "ANALYTICS_REQ_MANUAL", "status": "VALIDATED", "documentId": "DOC-X"},
                ],
            }))
            session.commit()

    @classmethod
    def tearDownClass(cls):
        with Session(engine) as session:
            session.query(ApplicationRow).filter(ApplicationRow.app_id == cls.APP_ID).delete(synchronize_session=False)
            session.commit()

    def test_report_shape_and_totals_agree_with_dashboard(self):
        report = _analytics()
        for section in ("applications", "requirements", "providers", "trends"):
            self.assertIn(section, report)
        overview = operations_overview(ADMIN)
        self.assertEqual(report["applications"]["total"], overview["applications"]["total"])
        for key in ("automaticallyVerified", "manuallyFulfilled", "citizenActionRequired", "officerReviewRequired", "retryInProgress"):
            self.assertEqual(report["applications"][key], overview["applications"][key], key)

    def test_requirement_and_fallback_counts_come_from_real_requirement_state(self):
        report = _analytics(start="2020-01-15", end="2020-01-15")
        self.assertEqual(report["applications"]["total"], 1)
        self.assertEqual(report["applications"]["manuallyFulfilled"], 1)
        reqs = report["requirements"]
        self.assertEqual(reqs["total"], 2)
        self.assertEqual(reqs["fulfilledAutomatically"], 1)
        self.assertEqual(reqs["fulfilledManually"], 1)
        self.assertEqual(reqs["fallbackUsed"], 1)

    def test_filters_are_applied_server_side(self):
        self.assertEqual(_analytics(start="2020-01-16", end="2020-01-16")["applications"]["total"], 0)
        by_requirement = _analytics(start="2020-01-15", end="2020-01-15", requirement="ANALYTICS_REQ_AUTO")
        self.assertEqual(by_requirement["requirements"]["total"], 1)
        by_provider = _analytics(start="2020-01-15", end="2020-01-15", provider="EDUCATION-DEPARTMENT")
        self.assertEqual(by_provider["applications"]["total"], 1, "a fallback attempt against a provider counts as touching it")
        self.assertEqual(by_provider["requirements"]["total"], 1, "requirement stats are scoped to what the provider handled")
        by_outcome = _analytics(start="2020-01-15", end="2020-01-15", outcome="automaticallyVerified")
        self.assertEqual(by_outcome["applications"]["total"], 0)

    def test_sparse_history_is_flagged_limited_not_fabricated(self):
        trend = _analytics(start="2020-01-15", end="2020-01-15")["trends"]["applications"]
        self.assertEqual(trend["series"], [{"date": "2020-01-15", "count": 1}])
        self.assertTrue(trend["limited"])

    def test_invalid_filters_are_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            _analytics(start="not-a-date")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            _analytics(outcome="made-up")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            _analytics(provider="NO-SUCH-PROVIDER")
        self.assertEqual(ctx.exception.status_code, 404)


class SchemeCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_catalogue_lists_exactly_the_persisted_schemes(self):
        schemes = admin_schemes(ADMIN)["schemes"]
        with Session(engine) as session:
            persisted = {row.scheme_id for row in session.query(SchemeCatalogRow).all()}
        self.assertEqual({s["schemeId"] for s in schemes}, persisted)
        for scheme in schemes:
            for field in ("name", "department", "active", "requirementCount", "providerCoverage", "applicationCount"):
                self.assertIn(field, scheme)

    def test_scheme_detail_requirements_match_persisted_rows_and_registry(self):
        from app.engine.adapters import integration_health
        from app.engine.registry import dependency_registry
        scheme_id = admin_schemes(ADMIN)["schemes"][0]["schemeId"]
        detail = admin_scheme_detail(scheme_id, user=ADMIN)
        with Session(engine) as session:
            persisted = [r.requirement_code for r in session.query(SchemeRequirementRow).filter_by(scheme_id=scheme_id).order_by(SchemeRequirementRow.id)]
        self.assertEqual([r["requirementCode"] for r in detail["requirements"]], persisted)
        registry = dependency_registry(integration_health())
        for requirement in detail["requirements"]:
            expected = {e["providerId"] for e in registry if e["requirementCode"] == requirement["requirementCode"]}
            self.assertEqual({p["providerId"] for p in requirement["eligibleProviders"]}, expected)
            self.assertEqual(requirement["manualUploadOnly"], not expected)

    def test_unknown_scheme_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            admin_scheme_detail("NO-SUCH-SCHEME", user=ADMIN)
        self.assertEqual(ctx.exception.status_code, 404)


class ProfileAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_profile_reflects_the_real_token_and_account(self):
        token = issue_token(ADMIN)
        request = SimpleNamespace(app=main.app)
        profile = admin_profile(request, credentials=SimpleNamespace(credentials=token), user=ADMIN)
        self.assertEqual(profile["user"], {"userId": "ADMIN_MH_01", "name": "Platform Administrator", "role": "ADMIN"})
        self.assertLess(profile["session"]["issuedAt"], profile["session"]["expiresAt"])
        self.assertFalse(profile["access"]["mutablePermissions"])

    def test_access_model_is_derived_from_enforced_route_guards(self):
        model = effective_access_model(main.app.routes)
        admin_area = next(a for a in model["areas"] if a["area"] == "/api/admin")
        self.assertGreater(admin_area["endpoints"], 0)
        self.assertEqual(admin_area["public"], 0, "no /api/admin endpoint may be unauthenticated")
        self.assertEqual(admin_area["byRole"], {"ADMIN": admin_area["endpoints"]}, "every /api/admin endpoint is ADMIN-only")

    def test_non_admin_roles_are_rejected_by_the_admin_guard(self):
        guard = require_roles("ADMIN")
        for role in ("CITIZEN", "OFFICER"):
            with self.assertRaises(HTTPException) as ctx:
                guard({"userId": f"{role}_X", "role": role})
            self.assertEqual(ctx.exception.status_code, 403)


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
