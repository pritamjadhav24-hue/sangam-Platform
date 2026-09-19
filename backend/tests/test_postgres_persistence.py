import unittest
import importlib.util
import asyncio
import threading
from types import SimpleNamespace
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.notification_manager import notification_manager
from app.core.persistence import (ApplicationConcurrencyError, ApplicationRow, DependencyRow,
                                  WorkflowHistoryRow, allocate_application_id, create_application, engine,
                                  get_application, get_dependency, hydrate_state, initialize,
                                  list_applications_for_citizen, list_dependencies_for_application,
                                  mark_application_write_authoritative, persist_state,
                                  transition_application_status, update_application_payload)
from app.engine.dependency_orchestrator import initiate_domicile
from app.engine.workflow_engine import APPLICATIONS, DEPENDENCIES, officer_action, transition_application


MIGRATION_0010_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0010_workflow_concurrency_metadata.py"
MIGRATION_0010_SPEC = importlib.util.spec_from_file_location("migration_0010", MIGRATION_0010_PATH)
MIGRATION_0010 = importlib.util.module_from_spec(MIGRATION_0010_SPEC)
MIGRATION_0010_SPEC.loader.exec_module(MIGRATION_0010)


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

    def test_application_repository_creation_and_database_id_allocation(self):
        with Session(engine) as session:
            application = create_application({
                "citizenId": "CITIZEN-REPOSITORY-WRITE",
                "serviceId": "SCH-MH-2026",
                "status": "DRAFT",
                "requirements": [],
            }, session=session)
            self.assertTrue(session.in_transaction())
            app_id = application["appId"]
            self.assertTrue(app_id.startswith("SCH-MH-2026-"))
            self.assertEqual(application["appId"], app_id)
            session.commit()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertIsNotNone(row)
            self.assertEqual(row.version, 1)
            self.assertIsNotNone(row.created_at)
            self.assertIsNotNone(row.updated_at)
            self.assertEqual(row.payload["requirements"], [])

    def test_application_repository_update_preserves_unpatched_payload_and_expected_version(self):
        app_id = "APP-REPOSITORY-WRITE-001"
        original = {"appId": app_id, "citizenId": "CITIZEN-REPOSITORY-WRITE", "status": "DRAFT", "requirements": [{"code": "IDENTITY"}], "eligibility": {"eligible": False}}
        create_application(original)
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            created_at = row.created_at
            version = row.version
        updated = update_application_payload(app_id, {"eligibility": {"eligible": True}}, expected_version=version)
        self.assertTrue(updated["eligibility"]["eligible"])
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.version, version + 1)
            self.assertEqual(row.created_at, created_at)
            self.assertGreater(row.updated_at, created_at)
            self.assertEqual(row.payload["requirements"], original["requirements"])
        with self.assertRaises(ApplicationConcurrencyError):
            update_application_payload(app_id, {"eligibility": {"eligible": False}}, expected_version=version)

    def test_application_repository_transition_updates_status_json_and_history_in_one_transaction(self):
        app_id = "APP-REPOSITORY-TRANSITION-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-REPOSITORY-WRITE", "status": "DRAFT", "statusHistory": []})
        with Session(engine) as session:
            session.begin()
            transitioned = transition_application_status(app_id, "IN_PROGRESS", actor="OFFICER", source="test", session=session)
            self.assertEqual(transitioned["status"], "IN_PROGRESS")
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.version, 2)
            self.assertTrue(session.in_transaction())
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 1)
            session.rollback()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.status, "DRAFT")
            self.assertEqual(row.version, 1)
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 0)

    def test_application_repository_row_lock_serializes_mutations(self):
        app_id = "APP-REPOSITORY-LOCK-WRITE-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-REPOSITORY-WRITE", "status": "DRAFT"})
        first = Session(engine)
        second = Session(engine)
        try:
            first.begin()
            transition_application_status(app_id, "IN_PROGRESS", session=first)
            second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with self.assertRaises(OperationalError):
                transition_application_status(app_id, "WAITING_FOR_USER", session=second)
            second.rollback()
            first.commit()
            transition_application_status(app_id, "WAITING_FOR_USER", session=second)
            second.commit()
        finally:
            first.close()
            second.close()
        self.assertEqual(get_application(app_id)["status"], "WAITING_FOR_USER")

    def test_application_id_allocation_serializes_across_sessions(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def allocate_in_session():
            try:
                with Session(engine) as session:
                    barrier.wait(timeout=5)
                    results.append(allocate_application_id("SCH-MH-2026", session=session))
                    session.commit()
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=allocate_in_session) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 2)

    def test_application_repository_does_not_use_stale_process_cache_or_fallback_on_db_failure(self):
        app_id = "APP-REPOSITORY-STALE-WRITE-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-REPOSITORY-WRITE", "status": "DRAFT", "requirements": [{"code": "IDENTITY"}]})
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-REPOSITORY-WRITE", "status": "COMPLETED", "requirements": []}
        update_application_payload(app_id, {"eligibility": {"eligible": True}})
        self.assertEqual(get_application(app_id)["status"], "DRAFT")
        self.assertEqual(get_application(app_id)["requirements"], [{"code": "IDENTITY"}])
        with patch("app.core.persistence.Session", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                update_application_payload(app_id, {"eligibility": {"eligible": False}})

    def test_application_write_marker_skips_only_explicit_snapshot_request(self):
        import main

        async def call_next(_request):
            return SimpleNamespace(status_code=200, headers={})

        migrated_request = SimpleNamespace(url=SimpleNamespace(path="/api/applications"), state=SimpleNamespace())
        mark_application_write_authoritative(migrated_request)
        with patch("main.persist_state") as persist:
            asyncio.run(main.persist_after_request(migrated_request, call_next))
            persist.assert_not_called()

        legacy_request = SimpleNamespace(url=SimpleNamespace(path="/api/legacy"), state=SimpleNamespace())
        with patch("main.persist_state") as persist:
            asyncio.run(main.persist_after_request(legacy_request, call_next))
            persist.assert_called_once()

    def test_checkpoint_2_metadata_schema_and_backfill(self):
        app_id = "APP-METADATA-001"
        dependency_id = "DEP-METADATA-001"
        long_required_data = "REQUIREMENT-" + ("x" * 4000)
        long_job_id = "JOB-" + ("j" * 4000)
        long_result_reference = "RESULT-" + ("r" * 4000)
        app_payload = {
            "appId": app_id,
            "citizenId": "CITIZEN-METADATA",
            "status": "DRAFT",
            "createdAt": "2026-02-01T10:00:00+05:30",
            "updatedAt": "2026-02-02T10:00:00+05:30",
            "requirements": [{"code": long_required_data}],
        }
        dependency_payload = {
            "dependencyId": dependency_id,
            "appId": app_id,
            "requiredData": long_required_data,
            "jobId": long_job_id,
            "jobStatus": "QUEUED",
            "resultReference": long_result_reference,
            "createdAt": "2026-02-01T10:00:00+05:30",
            "updatedAt": "2026-02-02T10:00:00+05:30",
        }
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-METADATA", status="DRAFT", payload=app_payload))
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status="QUEUED", payload=dependency_payload))
            session.commit()
            MIGRATION_0010._validate_existing_payloads(session.connection())
            MIGRATION_0010._backfill_existing_rows(session.connection())
            session.commit()
            app_row = session.get(ApplicationRow, app_id)
            dependency_row = session.get(DependencyRow, dependency_id)

        self.assertEqual(app_row.version, 1)
        self.assertEqual(dependency_row.version, 1)
        self.assertEqual(app_row.created_at.astimezone(timezone.utc).isoformat(), "2026-02-01T04:30:00+00:00")
        self.assertEqual(dependency_row.updated_at.astimezone(timezone.utc).isoformat(), "2026-02-02T04:30:00+00:00")
        self.assertEqual(dependency_row.required_data, long_required_data)
        self.assertEqual(dependency_row.job_id, long_job_id)
        self.assertEqual(dependency_row.job_status, "QUEUED")
        self.assertEqual(dependency_row.result_reference, long_result_reference)
        self.assertEqual(dependency_row.attempts, 0)
        self.assertEqual(dependency_row.max_attempts, 3)
        self.assertEqual(dependency_row.payload, dependency_payload)

    def test_checkpoint_2_missing_optional_dependency_fields_remain_null(self):
        app_id = "APP-METADATA-002"
        dependency_id = "DEP-METADATA-002"
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-METADATA", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-METADATA", "status": "DRAFT"}))
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status="WAITING_FOR_DEPENDENCY", payload={"dependencyId": dependency_id, "appId": app_id, "requiredData": "DOMICILE_PROOF"}))
            session.commit()
            MIGRATION_0010._validate_existing_payloads(session.connection())
            MIGRATION_0010._backfill_existing_rows(session.connection())
            session.commit()
            row = session.get(DependencyRow, dependency_id)
        self.assertIsNone(row.job_id)
        self.assertIsNone(row.job_status)
        self.assertIsNone(row.result_reference)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.max_attempts, 3)

    def test_checkpoint_2_invalid_legacy_values_fail_validation(self):
        bad_app_id = "APP-METADATA-BAD-TIMESTAMP"
        bad_dependency_id = "DEP-METADATA-BAD-RETRY"
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=bad_app_id, citizen_id="CITIZEN-METADATA", status="DRAFT", payload={"appId": bad_app_id, "createdAt": "not-a-timestamp"}))
            session.commit()
            with self.assertRaises(Exception):
                MIGRATION_0010._validate_existing_payloads(session.connection())
            session.rollback()
            session.delete(session.get(ApplicationRow, bad_app_id))
            session.commit()

            session.add(ApplicationRow(app_id="APP-METADATA-BAD-RETRY", citizen_id="CITIZEN-METADATA", status="DRAFT", payload={"appId": "APP-METADATA-BAD-RETRY"}))
            session.add(DependencyRow(dependency_id=bad_dependency_id, app_id="APP-METADATA-BAD-RETRY", status="QUEUED", payload={"dependencyId": bad_dependency_id, "requiredData": "DOMICILE_PROOF", "attempts": -1, "maxAttempts": 0}))
            session.commit()
            with self.assertRaises(Exception):
                MIGRATION_0010._validate_existing_payloads(session.connection())

    def test_checkpoint_2_indexes_and_phase_1_provider_job_columns_remain(self):
        inspector = inspect(engine)
        dependency_indexes = {index["name"] for index in inspector.get_indexes("dependencies")}
        self.assertIn("ix_dependencies_app_id_required_data", dependency_indexes)
        self.assertIn("ix_dependencies_job_id", dependency_indexes)
        provider_job_columns = {column["name"] for column in inspector.get_columns("provider_jobs")}
        self.assertTrue({"dispatch_attempts", "dispatch_claimed_until", "lease_owner", "lease_until"}.issubset(provider_job_columns))

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
