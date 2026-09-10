import unittest

from sqlalchemy import inspect, select

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.notification_manager import notification_manager
from app.core.persistence import ApplicationRow, DependencyRow, engine, hydrate_state, initialize, persist_state
from app.engine.workflow_engine import APPLICATIONS, DEPENDENCIES


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
        self.assertTrue({"applications", "dependencies", "consents", "workflow_history", "audit_entries", "notifications"}.issubset(tables))

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


if __name__ == "__main__":
    unittest.main()
