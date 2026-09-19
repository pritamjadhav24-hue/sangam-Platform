import unittest
from unittest.mock import patch

from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.notification_manager import notification_manager
from app.core.persistence import (ApplicationRow, DependencyRow, engine, get_application, get_dependency,
                                  hydrate_state, initialize, list_applications_for_citizen,
                                  list_dependencies_for_application, persist_state)
from app.engine.dependency_orchestrator import initiate_domicile
from app.engine.workflow_engine import APPLICATIONS, DEPENDENCIES, officer_action, transition_application


class PostgreSQLPersistenceTests(unittest.TestCase):
    def setUp(self):
        initialize()
        reset_demo_state()
        persist_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_connection_and_required_schema(self):
        tables = set(inspect(engine).get_table_names())
        self.assertTrue({"applications", "dependencies", "consents", "workflow_history", "audit_entries", "notifications", "user_accounts"}.issubset(tables))

    def test_application_repository_reads_postgresql_not_process_cache(self):
        app_id = "APP-REPOSITORY-001"
        persisted = {"appId": app_id, "citizenId": "CITIZEN-REPOSITORY", "status": "WAITING_FOR_DEPENDENCY", "requirements": [], "dependencies": []}
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id=persisted["citizenId"], status=persisted["status"], payload=persisted))
            session.commit()
        APPLICATIONS[app_id] = {**persisted, "status": "STALE_LOCAL_VALUE"}
        self.assertEqual(get_application(app_id)["status"], "WAITING_FOR_DEPENDENCY")
        self.assertEqual([item["appId"] for item in list_applications_for_citizen("CITIZEN-REPOSITORY")], [app_id])

    def test_dependency_repository_reads_postgresql_not_process_cache(self):
        app_id = "APP-REPOSITORY-002"
        dependency_id = "DEP-REPOSITORY-001"
        persisted = {"dependencyId": dependency_id, "appId": app_id, "requiredData": "DOMICILE_PROOF", "status": "QUEUED"}
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-REPOSITORY", status="WAITING_FOR_DEPENDENCY", payload={"appId": app_id, "citizenId": "CITIZEN-REPOSITORY", "status": "WAITING_FOR_DEPENDENCY"}))
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status=persisted["status"], payload=persisted))
            session.commit()
        DEPENDENCIES[dependency_id] = {**persisted, "status": "STALE_LOCAL_VALUE"}
        self.assertEqual(get_dependency(dependency_id)["status"], "QUEUED")
        self.assertEqual([item["dependencyId"] for item in list_dependencies_for_application(app_id)], [dependency_id])

    def test_repository_for_update_emits_row_lock(self):
        app_id = "APP-REPOSITORY-LOCK"
        dependency_id = "DEP-REPOSITORY-LOCK"
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-REPOSITORY", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-REPOSITORY", "status": "DRAFT"}))
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status="QUEUED", payload={"dependencyId": dependency_id, "appId": app_id, "status": "QUEUED"}))
            session.commit()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "applications" in statement.lower() or "dependencies" in statement.lower():
                statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.assertIsNotNone(get_application(app_id, for_update=True))
            self.assertIsNotNone(get_dependency(dependency_id, for_update=True))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertTrue(any("FOR UPDATE" in statement.upper() for statement in statements))

    def test_caller_owned_session_keeps_for_update_lock_until_rollback(self):
        app_id = "APP-REPOSITORY-TRANSACTION"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-REPOSITORY", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-REPOSITORY", "status": "DRAFT"}))
            setup.commit()

        first = Session(engine)
        second = Session(engine)
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            first.begin()
            self.assertEqual(get_application(app_id, for_update=True, session=first)["status"], "DRAFT")
            self.assertTrue(first.in_transaction())
            self.assertEqual(first.get_bind(), engine)
            self.assertEqual(get_application(app_id, session=first)["status"], "DRAFT")

            second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with self.assertRaises(OperationalError):
                second.execute(update(ApplicationRow).where(ApplicationRow.app_id == app_id).values(status="UPDATED"))
            second.rollback()

            first.rollback()
            second.execute(update(ApplicationRow).where(ApplicationRow.app_id == app_id).values(status="UPDATED"))
            second.commit()
            self.assertTrue(any("FOR UPDATE" in statement.upper() for statement in statements))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            first.close()
            second.close()

        self.assertEqual(get_application(app_id)["status"], "UPDATED")

    def test_repository_missing_and_database_failure_do_not_fall_back_to_cache(self):
        self.assertIsNone(get_application("APP-DOES-NOT-EXIST"))
        self.assertIsNone(get_dependency("DEP-DOES-NOT-EXIST"))
        APPLICATIONS["APP-DB-FAILURE"] = {"appId": "APP-DB-FAILURE", "status": "STALE_LOCAL_VALUE"}
        DEPENDENCIES["DEP-DB-FAILURE"] = {"dependencyId": "DEP-DB-FAILURE", "status": "STALE_LOCAL_VALUE"}
        with patch("app.core.persistence.Session", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                get_application("APP-DB-FAILURE")
            with self.assertRaises(RuntimeError):
                get_dependency("DEP-DB-FAILURE")

    def test_application_dependency_relationship_survives_roundtrip(self):
        app_id = "SCH-MH-2026-00142"
        dependency_id = "DEP-SCH-MH-2026-00142-001"
        app = {"appId": app_id, "citizenId": "CITIZEN_001", "status": "WAITING_FOR_DEPENDENCY", "statusHistory": [{"status": "DRAFT", "at": "2026-01-01T00:00:00+00:00"}], "dependencyIds": [dependency_id], "dependencies": [], "requirements": [], "eligibility": {"eligible": False}}
        dependency = {"dependencyId": dependency_id, "appId": app_id, "journeyId": app_id, "status": "WAITING_FOR_DEPENDENCY", "resultReference": None}
        app["dependencies"].append(dependency)
        APPLICATIONS[app_id] = app
        DEPENDENCIES[dependency_id] = dependency
        persist_state()
        APPLICATIONS.clear(); DEPENDENCIES.clear(); hydrate_state()
        self.assertEqual(APPLICATIONS[app_id]["status"], "WAITING_FOR_DEPENDENCY")
        self.assertEqual(DEPENDENCIES[dependency_id]["appId"], app_id)
        with engine.connect() as connection:
            self.assertIsNotNone(connection.execute(select(ApplicationRow).where(ApplicationRow.app_id == app_id)).first())
            self.assertIsNotNone(connection.execute(select(DependencyRow).where(DependencyRow.dependency_id == dependency_id)).first())

    def test_audit_and_notification_roundtrip(self):
        audit_bus.append("CITIZEN_001", "APPLICATION", "Persistence test", "SANGAM", "TEST", correlation_id="SCH-MH-2026-00142")
        notification_manager.add("CITIZEN_001", "CITIZEN", "TEST", "Persistence test", "Notification persisted.", {})
        persist_state()
        audit_bus.entries.clear(); notification_manager.notifications.clear(); hydrate_state()
        self.assertTrue(audit_bus.verify())
        self.assertEqual(notification_manager.notifications[0]["recipientUserId"], "CITIZEN_001")

    def test_demo_reset_removes_persisted_application(self):
        APPLICATIONS["SCH-MH-2026-00142"] = {"appId": "SCH-MH-2026-00142", "citizenId": "CITIZEN_001", "status": "DRAFT", "statusHistory": [], "dependencyIds": [], "dependencies": [], "requirements": [], "eligibility": {}}
        persist_state()
        reset_demo_state(); persist_state()
        with engine.connect() as connection:
            self.assertIsNone(connection.execute(select(ApplicationRow).where(ApplicationRow.app_id == "SCH-MH-2026-00142")).first())

    def test_invalid_terminal_transitions_are_rejected(self):
        for current, target in (("COMPLETED", "IN_PROGRESS"), ("COMPLETED", "SUBMITTED"), ("CANCELLED", "IN_PROGRESS"), ("APPROVED", "WAITING_FOR_DEPENDENCY")):
            app = {"appId": f"TEST-{current}", "citizenId": "CITIZEN_001", "status": current, "statusHistory": [], "createdAt": "2026-01-01T00:00:00+00:00"}
            with self.assertRaises(ValueError):
                transition_application(app, target)
            self.assertEqual(app["status"], current)

    def test_repeated_terminal_actions_are_idempotent(self):
        app_id = "SCH-MH-2026-00142"
        app = {"appId": app_id, "citizenId": "CITIZEN_001", "status": "COMPLETED", "statusHistory": [], "requirements": [], "timeline": [], "eligibility": {"eligible": True}}
        APPLICATIONS[app_id] = app
        self.assertIs(officer_action(app_id, "APPROVE", "Already approved"), app)
        dependency_id = "DEP-SCH-MH-2026-00142-001"
        dependency = {"dependencyId": dependency_id, "appId": app_id, "requiredData": "DOMICILE_PROOF", "status": "COMPLETED", "resultReference": "D-MH-9001", "attempts": 1, "maxAttempts": 3}
        app.update({"dependencyIds": [dependency_id], "dependencies": [dependency]}); DEPENDENCIES[dependency_id] = dependency
        self.assertFalse(initiate_domicile("CITIZEN_001", app)["success"] is False)


if __name__ == "__main__":
    unittest.main()
