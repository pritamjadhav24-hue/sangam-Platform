"""SANGAM as the only interoperability boundary, and the provider policy it
enforces: priority is not capability is not authorization.

Architecture tests read the source (imports only, never comments) so a
department reaching another department -- or SANGAM reaching a department
database -- fails the build. Policy, state and activity tests run against
the throwaway test database only.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.engine import provider_policy, requirement_fulfillment
from app.engine.adapters import AdapterResult
from app.engine.provider_policy import capability_authorization
from app.engine.registry import select_dependency_provider

APP = Path(__file__).resolve().parents[1] / "app"
BACKEND = APP.parent
DEPARTMENTS = ("revenue", "education", "social_welfare", "municipal_health", "transport",
               "agriculture", "labour", "food_civil_supplies", "housing", "skill_employment")
HTTP_CLIENTS = {"urllib.request", "requests", "httpx", "http.client", "aiohttp"}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def python_files(*roots: Path):
    for root in roots:
        yield from (root.rglob("*.py") if root.is_dir() else [root])


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_1_a_department_never_reaches_another_department(self):
        for key in DEPARTMENTS:
            own = f"app.sandbox.{key}"
            router = APP / "department_api" / "routers" / f"{key}.py"
            sandbox = [f for f in (APP / "sandbox" / key).glob("*.py")]
            for path in [router, *sandbox]:
                with self.subTest(path=path.name, department=key):
                    # app.sandbox.common is the shared sandbox framework (mixins, engine
                    # factory), not a department; anything else must be this department's own.
                    other = {name for name in imports_of(path) if name.startswith("app.sandbox.")
                             and not name.startswith(own) and name != "app.sandbox.common"}
                    self.assertEqual(other, set(), f"{path} imports another department: {other}")

    def test_1_department_services_hold_no_client_for_calling_other_services(self):
        for path in python_files(APP / "department_api", APP / "sandbox"):
            with self.subTest(path=str(path.relative_to(APP))):
                self.assertEqual(imports_of(path) & HTTP_CLIENTS, set(), f"{path} could call another service directly")

    def test_2_departments_do_not_depend_on_sangam_internals(self):
        # A department is its own system: it shares only synthetic seed data
        # (app.seeds), never SANGAM's engine, core or API.
        for path in python_files(APP / "department_api", APP / "sandbox"):
            with self.subTest(path=str(path.relative_to(APP))):
                sangam = {name for name in imports_of(path) if name.split(".")[:2] in (["app", "engine"], ["app", "core"], ["app", "api"])}
                self.assertEqual(sangam, set())

    def test_3_sangam_never_imports_department_databases_or_services(self):
        roots = [APP / "api", APP / "engine", APP / "core", BACKEND / "main.py", APP / "worker.py"]
        for path in python_files(*roots):
            with self.subTest(path=str(path.relative_to(BACKEND))):
                crossing = {name for name in imports_of(path) if name.startswith(("app.sandbox", "app.department_api"))}
                self.assertEqual(crossing, set(), f"{path} crosses into a department: {crossing}")


def _item(provider_id, provider, priority, authorization_payload, health="AVAILABLE", code="INCOME_PROOF"):
    return {"requirementCode": code, "providerId": provider_id, "provider": provider, "serviceId": f"S-{provider_id}", "priority": priority,
            "healthStatus": health, "authorization": capability_authorization(f"{provider_id}:{code}", {"authorization": authorization_payload} if authorization_payload is not None else {})}


class AuthorizationPolicyTests(unittest.TestCase):
    """7-10: priority orders valid providers; it never makes a provider valid."""

    REVENUE = ("REV-TEST", "Revenue", 10, {"authoritative": True})
    WELFARE = ("SW-TEST", "Social Welfare", 30, {"fallbackAuthorized": True})
    # Education *can* say something about income and has the best priority --
    # but it is not authorized for income.
    EDUCATION = ("EDU-TEST", "Education", 1, {"authoritative": False, "fallbackAuthorized": False})

    def _select(self, *items):
        with patch("app.engine.registry.dependency_registry", return_value=list(items)):
            return select_dependency_provider("INCOME_PROOF", [])

    def test_7_priority_selects_among_valid_providers(self):
        selected = self._select(_item(*self.REVENUE), _item(*self.WELFARE))
        self.assertEqual(selected["providerId"], "REV-TEST")

    def test_8_priority_does_not_override_authorization(self):
        selected = self._select(_item(*self.EDUCATION), _item(*self.REVENUE), _item(*self.WELFARE))
        self.assertEqual(selected["providerId"], "REV-TEST")

    def test_9_unauthorized_provider_is_never_a_fallback(self):
        selected = self._select(_item(*self.EDUCATION), _item(*self.REVENUE, health="UNAVAILABLE"))
        self.assertIsNone(selected, "Education must not answer for income just because Revenue is down")
        from app.engine import retry_policy
        with patch("app.engine.registry.dependency_registry", return_value=[_item(*self.EDUCATION), _item(*self.REVENUE, health="UNAVAILABLE")]), \
             patch("app.engine.adapters.integration_health", return_value=[]):
            self.assertIsNone(retry_policy.find_fallback_candidate("INCOME_PROOF", exclude_provider_ids={"REV-TEST"}))

    def test_10_authorized_fallback_is_used_when_the_authoritative_source_is_down(self):
        selected = self._select(_item(*self.EDUCATION), _item(*self.REVENUE, health="UNAVAILABLE"), _item(*self.WELFARE))
        self.assertEqual(selected["providerId"], "SW-TEST")
        self.assertEqual(selected["authorization"]["role"], "AUTHORIZED_FALLBACK")

    def test_an_authorized_fallback_never_outranks_an_authoritative_source(self):
        # Welfare given the "better" priority number still waits for Revenue.
        selected = self._select(_item("SW-TEST", "Social Welfare", 1, {"fallbackAuthorized": True}), _item(*self.REVENUE))
        self.assertEqual(selected["providerId"], "REV-TEST")

    def test_a_non_top_authorized_provider_may_be_called_but_an_unauthorized_one_never(self):
        from app.engine.adapters import service_is_authorized
        registry = [_item(*self.REVENUE), _item(*self.WELFARE), _item(*self.EDUCATION)]
        self.assertTrue(service_is_authorized("S-REV-TEST", "INCOME_PROOF", registry))
        self.assertTrue(service_is_authorized("S-SW-TEST", "INCOME_PROOF", registry), "the cascade must be able to ask the authorized fallback")
        self.assertFalse(service_is_authorized("S-EDU-TEST", "INCOME_PROOF", registry))
        self.assertFalse(service_is_authorized("S-REV-TEST", "CASTE_PROOF", registry))
        self.assertFalse(service_is_authorized("S-UNKNOWN", "INCOME_PROOF", registry))

    def test_policy_is_explicit_and_fails_closed(self):
        self.assertEqual(capability_authorization("SOCIAL-WELFARE-SANDBOX-INCOME:INCOME_PROOF", {})["role"], "AUTHORIZED_FALLBACK")
        self.assertEqual(capability_authorization("REVENUE-SANDBOX-INCOME:INCOME_PROOF", {})["role"], "AUTHORITATIVE")
        self.assertEqual(capability_authorization("REVENUE-SANDBOX-INCOME:INCOME_PROOF", {})["source"], "REGISTERED_DEFINITION")
        undeclared = capability_authorization("SOMEONE-NEW:INCOME_PROOF", {"priority": 1})
        self.assertEqual((undeclared["role"], undeclared["source"]), ("NOT_AUTHORIZED", "UNDECLARED"))
        # Data in the registry wins over the registered definition.
        revoked = capability_authorization("REVENUE-SANDBOX-INCOME:INCOME_PROOF", {"authorization": {"authoritative": False}})
        self.assertEqual((revoked["role"], revoked["source"]), ("NOT_AUTHORIZED", "REGISTRY"))


class CascadeSemanticsTests(unittest.TestCase):
    """5, 11, 12: citizen identity never picks the provider; no-record keeps
    searching authorized providers; an unasked provider is never "no record"."""

    REVENUE = _item("REV-TEST", "Revenue", 10, {"authoritative": True})
    WELFARE = _item("SW-TEST", "Social Welfare", 30, {"fallbackAuthorized": True})

    def _cascade(self, registry, first, answers, citizen_id="C1"):
        calls = []

        def call(service_id, citizen, **_kwargs):
            calls.append((service_id, citizen))
            return answers[service_id]

        def next_candidate(_code, exclude_provider_ids=()):
            ordered = sorted([i for i in registry if provider_policy.is_selectable(i) and i["healthStatus"] == "AVAILABLE"
                              and i["providerId"] not in exclude_provider_ids], key=provider_policy.selection_key)
            return ordered[0] if ordered else None

        with patch.object(requirement_fulfillment, "health_for_selection", return_value=[]), \
             patch.object(requirement_fulfillment, "select_dependency_provider", return_value=first), \
             patch.object(requirement_fulfillment, "dependency_registry", return_value=registry), \
             patch.object(requirement_fulfillment, "request_registered_service", side_effect=call), \
             patch.object(requirement_fulfillment.retry_policy, "find_fallback_candidate", side_effect=next_candidate), \
             patch.object(requirement_fulfillment, "audit_bus"):
            result, log = requirement_fulfillment._discover_and_retrieve("INCOME_PROOF", citizen_id, "APP-1", "APP-1", "CONSENT-1")
        return result, log, calls

    @staticmethod
    def _no_record():
        return AdapterResult(None, success=False, error_category="VALIDATION_ERROR", metadata={"recordNotFound": True})

    def test_5_citizen_identity_does_not_select_the_provider(self):
        chosen = set()
        for citizen in ("DEMO-CIT-001", "SYN-CIT-00031", "CITIZEN_001"):
            _, _, calls = self._cascade([self.REVENUE, self.WELFARE], self.REVENUE, {"S-REV-TEST": AdapterResult({"id": "R"}, success=True)}, citizen)
            chosen.add(calls[0][0])
        self.assertEqual(chosen, {"S-REV-TEST"})

    def test_11_no_record_continues_to_the_next_authorized_provider(self):
        result, log, _ = self._cascade([self.REVENUE, self.WELFARE], self.REVENUE,
                                       {"S-REV-TEST": self._no_record(), "S-SW-TEST": AdapterResult({"id": "W"}, success=True)})
        self.assertTrue(result.success)
        self.assertEqual([(e["providerId"], e.get("role")) for e in log], [("REV-TEST", "AUTHORITATIVE"), ("SW-TEST", "AUTHORIZED_FALLBACK")])

    def test_12_unavailable_provider_is_not_reported_as_no_record(self):
        # Revenue answers "no record", Welfare is down: that is not "no record anywhere".
        down_welfare = {**self.WELFARE, "healthStatus": "UNAVAILABLE"}
        result, log, _ = self._cascade([self.REVENUE, down_welfare], self.REVENUE, {"S-REV-TEST": self._no_record()})
        self.assertEqual(result.error_category, "UPSTREAM_UNAVAILABLE")
        self.assertTrue(result.retryable)
        self.assertTrue(any(entry.get("skipped") and entry["providerId"] == "SW-TEST" for entry in log))

    def test_no_record_everywhere_is_no_record(self):
        result, _, _ = self._cascade([self.REVENUE, self.WELFARE], self.REVENUE, {"S-REV-TEST": self._no_record(), "S-SW-TEST": self._no_record()})
        self.assertEqual(result.error_category, "VALIDATION_ERROR")
        self.assertTrue(result.metadata.get("recordNotFound"))


class VerificationStateTests(unittest.TestCase):
    """Distinct, explicit citizen states -- never everything as "no record"."""

    def state(self, **requirement):
        from app.api.citizen_routes import _verification_state
        return _verification_state({"code": "INCOME_PROOF", "dataType": "CERTIFICATE", **requirement})

    def test_each_failure_has_its_own_state(self):
        cases = [
            ("NOT_PROVIDED", None, {}, "NOT_STARTED"),
            ("VALIDATED", None, {"provenance": {"fallbackUsed": False}}, "VERIFIED"),
            ("VALIDATED", None, {"provenance": {"fallbackUsed": True}}, "VERIFIED_VIA_FALLBACK"),
            ("VALIDATED", None, {"documentId": "DOC-1"}, "UPLOADED"),
            ("FAILED", "VALIDATION_ERROR", {}, "NO_RECORD"),
            ("FAILED", "VALIDATION_ERROR", {"lookupOutcome": "AMBIGUOUS"}, "AMBIGUOUS_MATCH"),
            ("WAITING", "UPSTREAM_UNAVAILABLE", {}, "TEMPORARILY_UNAVAILABLE"),
            ("WAITING", "TIMEOUT", {}, "TIMEOUT"),
            ("FAILED", "AUTHORIZATION_ERROR", {}, "UNAUTHORIZED"),
            ("ACTION_REQUIRED", None, {}, "CONSENT_DENIED"),
            ("ACTION_REQUIRED", "IDENTITY_UNCONFIRMED", {}, "LOW_CONFIDENCE"),
            ("FAILED", "CONFIGURATION_ERROR", {}, "MANUAL_UPLOAD_REQUIRED"),
        ]
        for status, category, extra, expected in cases:
            with self.subTest(status=status, category=category, extra=extra):
                self.assertEqual(self.state(status=status, errorCategory=category, **extra), expected)

    def test_messages_distinguish_unavailable_from_no_record_and_offer_upload_only_when_possible(self):
        from app.api.citizen_routes import _requirement_user_action
        unavailable = _requirement_user_action({"code": "INCOME_PROOF", "dataType": "CERTIFICATE", "status": "WAITING", "errorCategory": "UPSTREAM_UNAVAILABLE"})
        no_record = _requirement_user_action({"code": "INCOME_PROOF", "dataType": "CERTIFICATE", "status": "FAILED", "errorCategory": "VALIDATION_ERROR"})
        self.assertTrue(unavailable.startswith("Government verification is temporarily unavailable."))
        self.assertTrue(no_record.startswith("No verified record was found in the connected departments."))
        identity = _requirement_user_action({"code": "IDENTITY", "dataType": "ATTRIBUTE", "status": "FAILED", "errorCategory": "VALIDATION_ERROR"})
        self.assertNotIn("upload", identity.lower())

    def test_department_records_accept_a_supporting_upload_but_identity_does_not(self):
        from app.api.citizen_routes import _can_upload
        self.assertTrue(_can_upload({"dataType": "RECORD"}))
        self.assertTrue(_can_upload({"dataType": "CERTIFICATE"}))
        self.assertFalse(_can_upload({"dataType": "ATTRIBUTE"}))


class AdminOperationsTests(unittest.TestCase):
    """23-27: outage, recovery, fallback, notifications and the activity timeline."""

    ADMIN = {"userId": "ADMIN_MH_01", "role": "ADMIN"}

    def setUp(self):
        # Work on an empty notification list so notices other test modules
        # left in the shared manager (about applications they deleted) do
        # not leak into these assertions or into a state snapshot.
        from app.core.notification_manager import notification_manager
        self.notifications = notification_manager
        self.saved = list(notification_manager.notifications)
        notification_manager.notifications.clear()
        self.before = 0

    def tearDown(self):
        self.notifications.notifications[:] = self.saved

    def _new(self, kind):
        return [item for item in self.notifications.notifications[self.before:] if item["type"] == kind and item["recipientUserId"] == "ADMIN_MH_01"]

    def test_23_24_outage_and_recovery_notify_admins_with_a_link_to_the_incident(self):
        from app.core.persistence import ProviderIncidentRow, engine, record_provider_health_transition
        from sqlalchemy.orm import Session
        system = "Architecture Test Provider"
        try:
            record_provider_health_transition(system, "Test", "svc", "AVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")
            record_provider_health_transition(system, "Test", "svc", "UNAVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")  # still down: no repeat
            down = self._new("PROVIDER_DOWN")
            self.assertEqual(len(down), 1)
            self.assertEqual(down[0]["target"]["kind"], "incident")
            self.assertTrue(down[0]["target"]["incidentId"].startswith("INC-"))
            record_provider_health_transition(system, "Test", "svc", "UNAVAILABLE", "AVAILABLE")
            recovered = self._new("PROVIDER_RECOVERED")
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["target"]["incidentId"], down[0]["target"]["incidentId"])
            # 26: mark as read, scoped to the administrator
            self.assertTrue(self.notifications.mark_read(down[0]["notificationId"], self.ADMIN)["read"])
            self.assertIsNone(self.notifications.mark_read(down[0]["notificationId"], {"userId": "OFFICER_MH_01", "role": "OFFICER"}))
        finally:
            with Session(engine) as session:
                session.query(ProviderIncidentRow).filter(ProviderIncidentRow.provider_system == system).delete(synchronize_session=False)
                session.commit()

    def test_operational_notice_about_an_authoritative_application_survives_a_state_snapshot(self):
        from app.core.persistence import ApplicationRow, NotificationRow, create_application, engine, persist_state
        from sqlalchemy.orm import Session
        app_id = "APP-NOTICE-PERSIST-1"
        try:
            with Session(engine) as session:
                create_application({"appId": app_id, "citizenId": "CITIZEN-NOTICE", "status": "IN_PROGRESS"}, session=session)
                session.commit()
            self.notifications.operational("APPLICATION_BLOCKED", "Application waiting", "waiting", dedupe_key=f"BLOCKED:{app_id}:X",
                                           severity="WARNING", app_id=app_id, target={"kind": "application"})
            notice = self._new("APPLICATION_BLOCKED")[0]
            self.assertEqual(notice["target"]["applicationId"], app_id)
            persist_state()
            with Session(engine) as session:
                stored = session.get(NotificationRow, notice["notificationId"])
                self.assertIsNotNone(stored, "operational notices must not be dropped by the legacy snapshot")
                self.assertEqual(stored.payload["target"]["applicationId"], app_id)
        finally:
            with Session(engine) as session:
                session.query(NotificationRow).filter(NotificationRow.notification_id.in_([n["notificationId"] for n in self._new("APPLICATION_BLOCKED")])).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id == app_id).delete(synchronize_session=False)
                session.commit()

    def test_repeated_failures_of_one_dependency_notify_once_and_mark_all_read_is_per_user(self):
        for attempt in range(3):
            self.notifications.handle({"type": "DEPENDENCY_RETRY_SCHEDULED", "eventId": f"EV-{attempt}", "payload": {"appId": "APP-RETRY-1", "dependencyId": "DEP-1"}})
        failures = self._new("INTEGRATION_FAILURE")
        self.assertEqual(len(failures), 1)
        self.assertNotIn("simulated", failures[0]["message"].lower())
        self.assertEqual(failures[0]["target"], {"kind": "application", "applicationId": "APP-RETRY-1"})
        self.assertEqual(self.notifications.mark_all_read({"userId": "OFFICER_MH_01", "role": "OFFICER"}), 0)
        self.assertGreaterEqual(self.notifications.mark_all_read(self.ADMIN), 1)
        self.assertTrue(all(item["read"] for item in self._new("INTEGRATION_FAILURE")))

    def _fallback_requirement(self):
        attempt_log = [
            {"providerId": "REVENUE-SANDBOX-INCOME", "provider": "Revenue", "skipped": True, "success": False, "role": "AUTHORITATIVE",
             "errorCategory": "UPSTREAM_UNAVAILABLE", "at": "2026-09-27T10:42:31+00:00"},
            {"providerId": "SOCIAL-WELFARE-SANDBOX-INCOME", "provider": "Welfare", "success": True, "role": "AUTHORIZED_FALLBACK",
             "at": "2026-09-27T10:42:31+00:00", "completedAt": "2026-09-27T10:42:32+00:00"},
        ]
        requirement = {"code": "INCOME_PROOF", "label": "Income proof", "status": "VALIDATED", "servedByRole": "AUTHORIZED_FALLBACK",
                       "canonical": {"incomeAmount": 315000}, "identityMatch": {"decision": "AUTO_ACCEPT", "matchCategory": "STRONG", "score": 1.0},
                       "provenance": {"fallbackUsed": True, "providerId": "SOCIAL-WELFARE-SANDBOX-INCOME", "verifiedAt": "2026-09-27T10:42:32+00:00"},
                       "fallbackAttempts": attempt_log}
        result = AdapterResult({"id": "SW-1"}, success=True)
        trace = requirement_fulfillment.interoperability_trace("APP-TRACE-1", requirement, "Higher Education Department", attempt_log, result, "2026-09-27T10:42:31+00:00")
        return requirement, trace

    def test_25_27_fallback_exchange_is_traced_through_sangam_and_sanitized(self):
        requirement, trace = self._fallback_requirement()
        stages = [step["stage"] for step in trace["steps"]]
        self.assertEqual(stages[:3], ["REQUEST", "REQUIREMENT", "REGISTRY"])
        for stage in ("PROVIDER_UNAVAILABLE", "FALLBACK_POLICY", "API_REQUEST", "API_RESPONSE", "ENTITY_RESOLUTION", "NORMALIZATION", "VERIFICATION", "RESULT", "RETURN"):
            self.assertIn(stage, stages)
        self.assertEqual(trace["outcome"], "AUTO_FILLED_VIA_FALLBACK")
        self.assertEqual(trace["consumerDepartment"], "Higher Education Department")
        # Source department -> SANGAM -> target department, never department -> department.
        self.assertEqual(trace["steps"][0]["target"], "SANGAM")
        self.assertEqual(trace["steps"][-1]["actor"], "SANGAM")
        text = str(trace)
        for secret in ("315000", "password", "token", "sangam_db", "revenue_db", "postgresql"):
            self.assertNotIn(secret, text)

    def test_25_fallback_notifies_admins_with_a_link_to_the_application(self):
        requirement, trace = self._fallback_requirement()
        requirement["trace"] = trace
        with patch.object(requirement_fulfillment, "audit_bus") as audit:
            requirement_fulfillment._after_exchange("APP-TRACE-1", requirement, "Higher Education Department")
        exchange = audit.append.call_args
        self.assertEqual(exchange.args[4], "INTEROP_EXCHANGE")
        payload = exchange.kwargs["payload"]
        self.assertEqual((payload["sourceDepartment"], payload["via"]), ("Higher Education Department", "SANGAM"))
        notice = self._new("FALLBACK_ACTIVATED")
        self.assertEqual(len(notice), 1)
        self.assertEqual(notice[0]["target"], {"kind": "application", "applicationId": "APP-TRACE-1", "providerId": "SOCIAL-WELFARE-SANDBOX-INCOME"})

    def test_27_activity_feed_reads_traces_from_the_authoritative_application(self):
        from app.core.admin_insights import interoperability_activity
        from app.core.persistence import ApplicationRow, create_application, engine
        from sqlalchemy.orm import Session
        requirement, trace = self._fallback_requirement()
        app_id = "APP-ACTIVITY-TEST-1"
        try:
            with Session(engine) as session:
                create_application({"appId": app_id, "citizenId": "CITIZEN-ACTIVITY", "status": "IN_PROGRESS",
                                    "requirements": [{**requirement, "trace": {**trace, "applicationId": app_id}}]}, session=session)
                session.commit()
            feed = interoperability_activity(application_id=app_id)
            self.assertEqual(feed["total"], 1)
            self.assertEqual(feed["summary"]["viaFallback"], 1)
            self.assertEqual(feed["exchanges"][0]["applicationId"], app_id)
        finally:
            with Session(engine) as session:
                session.query(ApplicationRow).filter(ApplicationRow.app_id == app_id).delete(synchronize_session=False)
                session.commit()


class AnyCitizenAnySchemeTests(unittest.TestCase):
    """4: citizens are not pre-mapped to departments -- any citizen can apply to
    every connected scheme; the requirement, not the person, decides who is asked."""

    def test_4_any_citizen_can_apply_to_every_connected_scheme(self):
        from app.api.citizen_routes import ApplySchemeRequest, apply_to_scheme
        from app.core.persistence import SchemeCatalogRow, engine
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            schemes = [row.scheme_id for row in session.query(SchemeCatalogRow).all()]
        self.assertGreaterEqual(len(schemes), 10)
        citizen = "CITIZEN-ANY-SCHEME-TEST"
        user = {"userId": citizen, "citizenId": citizen, "name": "Any Citizen", "role": "CITIZEN"}
        for scheme_id in schemes:
            with self.subTest(scheme=scheme_id):
                application = apply_to_scheme(ApplySchemeRequest(schemeId=scheme_id), SimpleNamespace(state=SimpleNamespace()), user=user)
                self.assertTrue(application["appId"])
                self.assertTrue(application["requirements"])


from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
