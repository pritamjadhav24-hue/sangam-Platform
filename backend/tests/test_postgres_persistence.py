import unittest
import importlib.util
import asyncio
import threading
import uuid
from types import SimpleNamespace
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, inspect, or_, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.audit_bus import audit_bus
from app.core.demo_state import reset_demo_state
from app.core.event_bus import event_bus
from app.core.notification_manager import notification_manager
from app.api.citizen_routes import get_citizen_application, list_citizen_applications
from app.core.persistence import (ApplicationAuthorityError, ApplicationConcurrencyError, ConsentConcurrencyError, ApplicationRow, AuditEntryRow, ConsentRow,
                                  ConflictReviewRow, CounterRow, DependencyRow, EntityReviewRow, EventRow,
                                  NotificationRow, WorkflowHistoryRow, allocate_application_id, create_application, engine,
                                  get_application, get_dependency, hydrate_state, initialize,
                                  list_applications_for_citizen, list_dependencies_for_application,
                                  mark_application_write_authoritative, persist_consent, persist_state, persist_transition,
                                  revoke_persisted_consent,
                                  mutate_application, mutate_workflow_aggregate, refresh_workflow_aggregate,
                                  transition_application_status, update_application_payload)
from app.engine.dependency_orchestrator import ensure_dependency, initiate_domicile
from app.engine import consent_manager
from app.engine.consent_manager import create_consent
from app.engine.workflow_engine import APPLICATIONS, DEPENDENCIES, ENTITY_REVIEWS, entity_review_action, officer_action, transition_application


MIGRATION_0010_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0010_workflow_concurrency_metadata.py"
MIGRATION_0010_SPEC = importlib.util.spec_from_file_location("migration_0010", MIGRATION_0010_PATH)
MIGRATION_0010 = importlib.util.module_from_spec(MIGRATION_0010_SPEC)
MIGRATION_0010_SPEC.loader.exec_module(MIGRATION_0010)


class PostgreSQLPersistenceTests(unittest.TestCase):
    def _clear_authoritative_rows(self):
        with Session(engine) as session:
            app_ids = [row.app_id for row in session.query(ApplicationRow).filter(ApplicationRow.authoritative_at.is_not(None)).all()]
            if app_ids:
                for model, column in (
                    (WorkflowHistoryRow, WorkflowHistoryRow.app_id),
                    (DependencyRow, DependencyRow.app_id),
                    (EntityReviewRow, EntityReviewRow.app_id),
                    (ConflictReviewRow, ConflictReviewRow.app_id),
                ):
                    session.query(model).filter(column.in_(app_ids)).delete(synchronize_session=False)
                session.query(ConsentRow).filter(ConsentRow.app_id.in_(app_ids)).delete(synchronize_session=False)
                session.query(NotificationRow).filter(NotificationRow.app_id.in_(app_ids)).delete(synchronize_session=False)
                session.query(EventRow).filter(EventRow.app_id.in_(app_ids)).delete(synchronize_session=False)
                session.query(AuditEntryRow).filter(AuditEntryRow.correlation_id.in_(app_ids)).delete(synchronize_session=False)
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(app_ids)).delete(synchronize_session=False)
                session.commit()

    def setUp(self):
        initialize()
        self._clear_authoritative_rows()
        reset_demo_state()
        persist_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()
        self._clear_authoritative_rows()

    def test_connection_and_required_schema(self):
        tables = set(inspect(engine).get_table_names())
        self.assertTrue({"applications", "dependencies", "consents", "workflow_history", "audit_entries", "notifications", "user_accounts"}.issubset(tables))

    def test_consent_version_starts_at_one_and_direct_mutations_increment_once(self):
        citizen_id = f"CITIZEN-CONSENT-VERSION-{uuid.uuid4().hex}"
        receipt = create_consent(citizen_id, True)
        consent_id = receipt["consentId"]
        with Session(engine) as session:
            self.assertEqual(session.get(ConsentRow, consent_id).version, 1)
        receipt["allowed"] = ["Income status"]
        persist_consent(receipt)
        with Session(engine) as session:
            self.assertEqual(session.get(ConsentRow, consent_id).version, 2)
        revoke_persisted_consent(citizen_id, consent_id)
        with Session(engine) as session:
            self.assertEqual(session.get(ConsentRow, consent_id).version, 3)

    def test_hydration_retains_source_versions_for_multiple_historical_rows(self):
        citizen_id = f"CITIZEN-CONSENT-HISTORY-{uuid.uuid4().hex}"
        first = f"CONSENT-HISTORY-A-{uuid.uuid4().hex}"
        second = f"CONSENT-HISTORY-B-{uuid.uuid4().hex}"
        with Session(engine) as session:
            session.add(ConsentRow(consent_id=first, citizen_id=citizen_id, version=4, payload={"consentId": first, "citizenId": citizen_id}))
            session.add(ConsentRow(consent_id=second, citizen_id=citizen_id, version=7, payload={"consentId": second, "citizenId": citizen_id}))
            session.commit()
        hydrate_state()
        self.assertEqual(consent_manager.CONSENT_SOURCE_VERSIONS[first], 4)
        self.assertEqual(consent_manager.CONSENT_SOURCE_VERSIONS[second], 7)
        self.assertEqual(consent_manager.CONSENTS_BY_ID[first]["_source_version"], 4)
        self.assertEqual(consent_manager.CONSENTS_BY_ID[second]["_source_version"], 7)
        self.assertIsNone(consent_manager.current(citizen_id))

    def test_snapshot_updates_matching_version_without_double_increment(self):
        citizen_id = f"CITIZEN-CONSENT-SNAPSHOT-{uuid.uuid4().hex}"
        receipt = create_consent(citizen_id, True)
        consent_id = receipt["consentId"]
        persist_state()
        with Session(engine) as session:
            self.assertEqual(session.get(ConsentRow, consent_id).version, 1)
        receipt["marker"] = "snapshot"
        persist_state()
        with Session(engine) as session:
            row = session.get(ConsentRow, consent_id)
            self.assertEqual(row.version, 2)
            self.assertEqual(row.payload["marker"], "snapshot")
        persist_state()
        with Session(engine) as session:
            self.assertEqual(session.get(ConsentRow, consent_id).version, 2)

    def test_stale_snapshot_is_rejected_without_overwriting_newer_database_row(self):
        citizen_id = f"CITIZEN-CONSENT-STALE-{uuid.uuid4().hex}"
        receipt = create_consent(citizen_id, True)
        consent_id = receipt["consentId"]
        stale = dict(receipt)
        revoke_persisted_consent(citizen_id, consent_id)
        consent_manager.CONSENTS[citizen_id] = stale
        with self.assertRaises(ConsentConcurrencyError):
            persist_state()
        with Session(engine) as session:
            row = session.get(ConsentRow, consent_id)
            self.assertEqual(row.version, 2)
            self.assertEqual(row.payload["decision"], "REVOKED")

    def test_concurrent_mutation_wins_over_stale_snapshot(self):
        citizen_id = f"CITIZEN-CONSENT-RACE-{uuid.uuid4().hex}"
        receipt = create_consent(citizen_id, True)
        consent_id = receipt["consentId"]
        stale = dict(receipt)
        first = Session(engine)
        first.begin()
        row = first.get(ConsentRow, consent_id, with_for_update=True)
        row.payload = {**row.payload, "marker": "transaction-a"}
        row.version = 2
        finished = threading.Event()
        errors = []

        def snapshot():
            consent_manager.CONSENTS[citizen_id] = stale
            try:
                persist_state()
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=snapshot)
        thread.start()
        self.assertFalse(finished.wait(timeout=0.25))
        first.commit()
        first.close()
        thread.join(timeout=5)
        self.assertTrue(finished.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ConsentConcurrencyError)
        with Session(engine) as session:
            row = session.get(ConsentRow, consent_id)
            self.assertEqual(row.version, 2)
            self.assertEqual(row.payload["marker"], "transaction-a")

    def test_snapshot_rollback_does_not_advance_version_or_local_source(self):
        citizen_id = f"CITIZEN-CONSENT-ROLLBACK-{uuid.uuid4().hex}"
        receipt = create_consent(citizen_id, True)
        consent_id = receipt["consentId"]
        receipt["marker"] = "rollback-candidate"
        with patch("app.core.persistence.Session.commit", side_effect=RuntimeError("forced snapshot failure")):
            with self.assertRaises(RuntimeError):
                persist_state()
        with Session(engine) as session:
            row = session.get(ConsentRow, consent_id)
            self.assertEqual(row.version, 1)
            self.assertNotIn("marker", row.payload)
        self.assertEqual(receipt["_source_version"], 1)

    def test_missing_local_consent_does_not_delete_database_row(self):
        citizen_id = f"CITIZEN-CONSENT-MISSING-{uuid.uuid4().hex}"
        consent_id = f"CONSENT-MISSING-{uuid.uuid4().hex}"
        with Session(engine) as session:
            session.add(ConsentRow(consent_id=consent_id, citizen_id=citizen_id, version=2, payload={"consentId": consent_id, "citizenId": citizen_id}))
            session.commit()
        consent_manager.CONSENTS.pop(citizen_id, None)
        persist_state()
        with Session(engine) as session:
            self.assertIsNotNone(session.get(ConsentRow, consent_id))

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

    def test_application_repository_writes_mark_authority_and_preserve_marker(self):
        app_id = "APP-AUTHORITY-MARKER-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "DRAFT"})
        with Session(engine) as session:
            marker = session.get(ApplicationRow, app_id).authoritative_at
        update_application_payload(app_id, {"eligibility": {"eligible": True}})
        transition_application_status(app_id, "IN_PROGRESS", source="test")
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertIsNotNone(row.authoritative_at)
            self.assertEqual(row.authoritative_at, marker)

    def test_migration_0011_adds_nullable_authority_boundary(self):
        columns = {column["name"]: column for column in inspect(engine).get_columns("applications")}
        self.assertIn("authoritative_at", columns)
        self.assertTrue(columns["authoritative_at"]["nullable"])
        indexes = {index["name"] for index in inspect(engine).get_indexes("applications")}
        self.assertIn("ix_applications_authoritative_at", indexes)

    def test_persist_state_cannot_replace_authoritative_application_or_children(self):
        app_id = "APP-AUTHORITY-PROTECTED-001"
        dependency_id = "DEP-AUTHORITY-PROTECTED-001"
        review_id = "REVIEW-AUTHORITY-PROTECTED-001"
        conflict_id = "CONFLICT-AUTHORITY-PROTECTED-001"
        consent_id = "CONSENT-AUTHORITY-PROTECTED-001"
        notification_id = "NOTIFICATION-AUTHORITY-PROTECTED-001"
        with Session(engine) as session:
            app = create_application({"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "DRAFT"}, session=session)
            session.add(WorkflowHistoryRow(app_id=app_id, status="DRAFT", occurred_at="2026-01-01T00:00:00+00:00", payload={"source": "postgres"}))
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status="QUEUED", payload={"dependencyId": dependency_id, "appId": app_id, "status": "QUEUED", "source": "postgres"}))
            session.add(EntityReviewRow(review_id=review_id, app_id=app_id, payload={"reviewId": review_id, "appId": app_id, "source": "postgres"}))
            session.add(ConflictReviewRow(review_id=conflict_id, app_id=app_id, payload={"reviewId": conflict_id, "appId": app_id, "source": "postgres"}))
            session.add(ConsentRow(consent_id=consent_id, citizen_id="CITIZEN-AUTHORITY", app_id=app_id, payload={"consentId": consent_id, "source": "postgres"}))
            session.add(NotificationRow(notification_id=notification_id, recipient_user_id="CITIZEN-AUTHORITY", app_id=app_id, payload={"notificationId": notification_id, "applicationId": app_id, "source": "postgres"}))
            session.add(EventRow(app_id=app_id, event_type="POSTGRES_EVENT", occurred_at="2026-01-01T00:00:00+00:00", payload={"source": "postgres"}))
            session.add(AuditEntryRow(sequence=990001, correlation_id=app_id, consent_id=consent_id, payload={"source": "postgres"}))
            session.commit()

        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "STALE_LOCAL", "source": "local"}
        DEPENDENCIES[dependency_id] = {"dependencyId": dependency_id, "appId": app_id, "status": "STALE_LOCAL"}
        persist_state()

        with Session(engine) as session:
            self.assertEqual(session.get(ApplicationRow, app_id).status, "DRAFT")
            self.assertEqual(session.get(DependencyRow, dependency_id).payload["source"], "postgres")
            self.assertEqual(session.get(EntityReviewRow, review_id).payload["source"], "postgres")
            self.assertEqual(session.get(ConflictReviewRow, conflict_id).payload["source"], "postgres")
            self.assertEqual(session.get(ConsentRow, consent_id).payload["source"], "postgres")
            self.assertEqual(session.get(NotificationRow, notification_id).payload["source"], "postgres")
            self.assertEqual(session.query(EventRow).filter(EventRow.app_id == app_id).one().payload["source"], "postgres")
            self.assertEqual(session.get(AuditEntryRow, 990001).payload["source"], "postgres")

    def test_persist_state_preserves_application_counter_high_water_mark(self):
        with Session(engine) as session:
            counter = session.get(CounterRow, "application")
            counter.next_value = 900000
            session.commit()
        persist_state()
        with Session(engine) as session:
            counter = session.get(CounterRow, "application")
            self.assertGreaterEqual(counter.next_value, 900000)

    def test_repository_write_waits_for_snapshot_style_application_row_lock(self):
        app_id = "APP-AUTHORITY-RACE-REPOSITORY-FIRST"
        create_application({"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "DRAFT"})
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "STALE_LOCAL"}
        first = Session(engine)
        first.begin()
        update_application_payload(app_id, {"fromRepository": True}, session=first)
        errors = []
        finished = threading.Event()

        def snapshot():
            try:
                persist_state()
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=snapshot)
        thread.start()
        self.assertFalse(finished.wait(timeout=0.25))
        first.commit()
        thread.join(timeout=5)
        first.close()
        self.assertFalse(errors)
        self.assertTrue(finished.is_set())
        with Session(engine) as session:
            self.assertTrue(session.get(ApplicationRow, app_id).payload["fromRepository"])

    def test_repository_write_after_snapshot_style_lock_serializes_then_succeeds(self):
        app_id = "APP-AUTHORITY-RACE-SNAPSHOT-FIRST"
        create_application({"appId": app_id, "citizenId": "CITIZEN-AUTHORITY", "status": "DRAFT"})
        snapshot_session = Session(engine)
        snapshot_session.begin()
        snapshot_session.execute(select(ApplicationRow).where(ApplicationRow.app_id == app_id).with_for_update()).scalar_one()
        errors = []
        finished = threading.Event()

        def repository_write():
            try:
                update_application_payload(app_id, {"afterSnapshot": True})
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=repository_write)
        thread.start()
        self.assertFalse(finished.wait(timeout=0.25))
        snapshot_session.commit()
        snapshot_session.close()
        thread.join(timeout=5)
        self.assertFalse(errors)
        self.assertTrue(finished.is_set())
        self.assertTrue(get_application(app_id)["afterSnapshot"])

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

    def test_application_mutation_gateway_is_database_only_and_caller_controls_commit(self):
        app_id = "APP-MUTATION-GATEWAY-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "DRAFT", "payloadValue": "old"})
        with Session(engine) as session:
            version = session.get(ApplicationRow, app_id).version
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "STALE_LOCAL", "payloadValue": "stale"}
        with Session(engine) as session:
            session.begin()
            result = mutate_application(app_id, {"payloadValue": "fresh"}, expected_version=version, session=session)
            self.assertTrue(session.in_transaction())
            self.assertEqual(result["payloadValue"], "fresh")
            self.assertEqual(APPLICATIONS[app_id]["payloadValue"], "stale")
            with Session(engine) as other:
                self.assertEqual(other.get(ApplicationRow, app_id).payload["payloadValue"], "old")
            session.commit()
        self.assertEqual(get_application(app_id)["payloadValue"], "fresh")
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertIsNotNone(row.authoritative_at)
            self.assertEqual(row.payload["updatedAt"], row.updated_at.astimezone(timezone.utc).isoformat())

    def test_application_mutation_gateway_rolls_back_without_establishing_authority(self):
        app_id = "APP-MUTATION-GATEWAY-ROLLBACK-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "DRAFT", "payloadValue": "old"})
        with Session(engine) as session:
            session.begin()
            before = session.get(ApplicationRow, app_id)
            before_version = before.version
            before_authority = before.authoritative_at
            before_updated = before.updated_at
            mutate_application(app_id, {"payloadValue": "rolled-back"}, expected_version=before_version, session=session)
            session.rollback()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.payload["payloadValue"], "old")
            self.assertEqual(row.version, before_version)
            self.assertEqual(row.authoritative_at, before_authority)
            self.assertEqual(row.updated_at, before_updated)

    def test_application_mutation_gateway_rejects_reserved_fields(self):
        app_id = "APP-MUTATION-GATEWAY-RESERVED-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "DRAFT"})
        with self.assertRaises(ValueError):
            mutate_application(app_id, {"status": "COMPLETED"})
        with self.assertRaises(ValueError):
            mutate_application(app_id, {"authoritative_at": "forged"})

    def test_application_mutation_gateway_same_version_writers_serialize(self):
        app_id = "APP-MUTATION-GATEWAY-RACE-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "DRAFT"})
        with Session(engine) as session:
            version = session.get(ApplicationRow, app_id).version
        first = Session(engine)
        finished = threading.Event()
        errors = []
        try:
            first.begin()
            mutate_application(app_id, {"writer": "first"}, expected_version=version, session=first)

            def second_writer():
                with Session(engine) as second:
                    try:
                        mutate_application(app_id, {"writer": "second"}, expected_version=version, session=second)
                    except Exception as error:
                        errors.append(error)
                    finally:
                        second.rollback()
                        finished.set()

            thread = threading.Thread(target=second_writer)
            thread.start()
            self.assertFalse(finished.wait(timeout=0.25))
            first.commit()
            thread.join(timeout=5)
            self.assertTrue(finished.is_set())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ApplicationConcurrencyError)
        finally:
            first.close()

    def test_application_mutation_gateway_survives_snapshot_and_legacy_writes(self):
        app_id = "APP-MUTATION-GATEWAY-FENCE-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "DRAFT", "payloadValue": "old"})
        mutate_application(app_id, {"payloadValue": "authoritative"})
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "STALE_LOCAL", "payloadValue": "stale"}
        persist_state()
        with self.assertRaises(ApplicationAuthorityError):
            persist_transition({"appId": app_id, "citizenId": "CITIZEN-GATEWAY", "status": "IN_PROGRESS", "payloadValue": "legacy"}, {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00"})
        self.assertEqual(get_application(app_id)["payloadValue"], "authoritative")

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

    def test_legacy_persist_transition_still_updates_legacy_application(self):
        app_id = "APP-LEGACY-FENCE-001"
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-FENCE", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT"}))
            session.commit()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertIsNone(row.authoritative_at)
            history = {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00", "source": "test"}
        persist_transition({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "IN_PROGRESS", "updatedAt": history["at"]}, history)
        with Session(engine) as session:
            self.assertEqual(session.get(ApplicationRow, app_id).status, "IN_PROGRESS")
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 1)

    def test_legacy_persist_transition_rejects_authoritative_application_without_mutation(self):
        app_id = "APP-AUTHORITY-FENCE-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT", "payloadValue": "authoritative"})
        with Session(engine) as session:
            before = session.get(ApplicationRow, app_id)
            before_version = before.version
            before_payload = dict(before.payload)
            before_status = before.status
            before_history = session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count()
        with self.assertRaises(ApplicationAuthorityError):
            persist_transition({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "IN_PROGRESS", "payloadValue": "stale"}, {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00"})
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.status, before_status)
            self.assertEqual(row.version, before_version)
            self.assertEqual(row.payload, before_payload)
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), before_history)

    def test_stale_legacy_persist_transition_is_rejected_after_authoritative_repository_update(self):
        app_id = "APP-AUTHORITY-FENCE-002"
        create_application({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT", "payloadValue": "old"})
        stale = {"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT", "payloadValue": "old"}
        update_application_payload(app_id, {"payloadValue": "fresh"})
        with self.assertRaises(ApplicationAuthorityError):
            persist_transition({**stale, "status": "IN_PROGRESS"}, {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00"})
        self.assertEqual(get_application(app_id)["payloadValue"], "fresh")

    def test_real_two_session_authority_race_blocks_then_rejects_legacy_writer(self):
        app_id = "APP-AUTHORITY-FENCE-RACE-001"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-FENCE", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT", "payloadValue": "old"}))
            setup.commit()
        first = Session(engine)
        first.begin()
        update_application_payload(app_id, {"payloadValue": "fresh"}, session=first)
        errors = []
        finished = threading.Event()

        def legacy_writer():
            try:
                persist_transition({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "IN_PROGRESS", "payloadValue": "stale"}, {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00"})
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=legacy_writer)
        thread.start()
        self.assertFalse(finished.wait(timeout=0.25))
        first.commit()
        first.close()
        thread.join(timeout=5)
        self.assertTrue(finished.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ApplicationAuthorityError)
        self.assertEqual(get_application(app_id)["payloadValue"], "fresh")

    def test_legacy_writer_first_then_authoritative_repository_write_remains_consistent(self):
        app_id = "APP-AUTHORITY-FENCE-RACE-002"
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-FENCE", status="DRAFT", payload={"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT"}))
            session.commit()
        persist_transition({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "IN_PROGRESS"}, {"status": "IN_PROGRESS", "at": "2026-01-01T00:00:00+00:00"})
        update_application_payload(app_id, {"payloadValue": "authoritative"})
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertIsNotNone(row.authoritative_at)
            self.assertEqual(row.status, "IN_PROGRESS")
            self.assertEqual(row.payload["payloadValue"], "authoritative")

    def test_transition_application_authority_rejection_leaves_local_state_unchanged(self):
        app_id = "APP-AUTHORITY-FENCE-ROLLBACK-001"
        authoritative = create_application({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "DRAFT"})
        local = {**authoritative, "statusHistory": [{"status": "DRAFT", "at": authoritative["createdAt"]}]}
        APPLICATIONS[app_id] = local
        with self.assertRaises(ApplicationAuthorityError):
            transition_application(local, "IN_PROGRESS")
        self.assertEqual(local["status"], "DRAFT")
        self.assertEqual(local["statusHistory"], [{"status": "DRAFT", "at": authoritative["createdAt"]}])
        self.assertEqual(local["updatedAt"], authoritative["updatedAt"])

    def test_officer_authority_rejection_does_not_leave_officer_remarks(self):
        app_id = "APP-AUTHORITY-FENCE-OFFICER-001"
        authoritative = create_application({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "WAITING_FOR_OFFICER"})
        local = {**authoritative, "requirements": [], "entityReviews": [], "conflictReviews": [], "timeline": [], "officerRemarks": None}
        APPLICATIONS[app_id] = local
        with self.assertRaises(ApplicationAuthorityError):
            officer_action(app_id, "REQUEST_INFO", "should not persist")
        self.assertIsNone(local["officerRemarks"])
        self.assertEqual(local["status"], "WAITING_FOR_OFFICER")

    def test_dependency_creation_preflight_rejects_authoritative_application_before_local_mutation(self):
        app_id = "APP-AUTHORITY-FENCE-DEPENDENCY-001"
        authoritative = create_application({"appId": app_id, "citizenId": "CITIZEN-FENCE", "status": "IN_PROGRESS"})
        local = {**authoritative, "dependencyIds": [], "dependencies": []}
        APPLICATIONS[app_id] = local
        with self.assertRaises(ApplicationAuthorityError):
            ensure_dependency(local, "DOMICILE_PROOF")
        self.assertEqual(local["dependencyIds"], [])
        self.assertEqual(local["dependencies"], [])
        self.assertFalse(any(dependency.get("appId") == app_id for dependency in DEPENDENCIES.values()))

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

    def test_citizen_application_list_reads_postgresql_and_database_dependencies(self):
        app_id = "APP-CITIZEN-LIST-001"
        dependency_id = "DEP-CITIZEN-LIST-001"
        with Session(engine) as session:
            create_application({
                "appId": app_id, "citizenId": "CITIZEN-API", "status": "WAITING_FOR_DEPENDENCY",
                "dependencies": [{"status": "STALE_LOCAL", "providerId": "INTERNAL"}],
            }, session=session)
            session.add(DependencyRow(
                dependency_id=dependency_id, app_id=app_id, status="COMPLETED",
                attempts=2, max_attempts=3,
                payload={"dependencyId": dependency_id, "appId": app_id, "requiredService": "Income verification", "status": "COMPLETED", "attempts": 2, "maxAttempts": 3, "providerId": "PROVIDER-INTERNAL", "adapter": "internal"},
            ))
            session.commit()
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-API", "status": "STALE_LOCAL", "dependencies": [{"status": "STALE_LOCAL"}]}

        response = list_citizen_applications({"role": "CITIZEN", "citizenId": "CITIZEN-API"})

        self.assertEqual(len(response["applications"]), 1)
        application = response["applications"][0]
        self.assertEqual(application["status"], "WAITING_FOR_DEPENDENCY")
        self.assertEqual(application["dependencies"], [{"requiredService": "Income verification", "status": "COMPLETED", "attempts": 2, "maxAttempts": 3}])
        self.assertNotIn("providerId", str(application))
        self.assertNotIn("adapter", str(application))

    def test_citizen_application_detail_reads_postgresql_and_enforces_database_ownership(self):
        app_id = "APP-CITIZEN-DETAIL-001"
        with Session(engine) as session:
            create_application({"appId": app_id, "citizenId": "CITIZEN-API", "status": "DRAFT", "requirements": [{"code": "INCOME_PROOF", "source": "internal", "recordId": "RAW-1"}]}, session=session)
            session.commit()
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-OTHER", "status": "STALE_LOCAL", "requirements": []}

        response = get_citizen_application(app_id, {"role": "CITIZEN", "citizenId": "CITIZEN-API"})
        self.assertEqual(response["status"], "DRAFT")
        self.assertEqual(response["requirements"][0]["requirementCode"], "INCOME_PROOF")
        self.assertNotIn("recordId", str(response))

        with self.assertRaises(Exception) as error:
            get_citizen_application(app_id, {"role": "CITIZEN", "citizenId": "CITIZEN-OTHER"})
        self.assertEqual(getattr(error.exception, "status_code", None), 404)

        with self.assertRaises(Exception) as error:
            get_citizen_application("APP-CITIZEN-MISSING", {"role": "CITIZEN", "citizenId": "CITIZEN-API"})
        self.assertEqual(getattr(error.exception, "status_code", None), 404)

    def test_citizen_application_reads_have_no_local_fallback_on_database_failure(self):
        APPLICATIONS["APP-CITIZEN-DB-FAILURE"] = {"appId": "APP-CITIZEN-DB-FAILURE", "citizenId": "CITIZEN-API", "status": "STALE_LOCAL"}
        with patch("app.api.citizen_routes.list_applications_for_citizen", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                list_citizen_applications({"role": "CITIZEN", "citizenId": "CITIZEN-API"})
        with patch("app.api.citizen_routes.get_application", side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                get_citizen_application("APP-CITIZEN-DB-FAILURE", {"role": "CITIZEN", "citizenId": "CITIZEN-API"})

    def test_citizen_application_detail_remains_postgresql_authoritative_after_snapshot_and_reload(self):
        app_id = "APP-CITIZEN-RELOAD-001"
        with Session(engine) as session:
            create_application({"appId": app_id, "citizenId": "CITIZEN-API", "status": "DRAFT"}, session=session)
            session.commit()
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-API", "status": "STALE_LOCAL"}
        persist_state()
        APPLICATIONS.clear()
        hydrate_state()
        APPLICATIONS[app_id]["status"] = "STALE_AFTER_RELOAD"
        self.assertEqual(get_citizen_application(app_id, {"role": "CITIZEN", "citizenId": "CITIZEN-API"})["status"], "DRAFT")

    def test_citizen_application_read_sees_only_committed_repository_updates(self):
        app_id = "APP-CITIZEN-CONCURRENT-001"
        create_application({"appId": app_id, "citizenId": "CITIZEN-API", "status": "DRAFT"})
        first = Session(engine)
        try:
            first.begin()
            update_application_payload(app_id, {"eligibility": {"eligible": True}}, session=first)
            self.assertNotIn("eligibility", get_citizen_application(app_id, {"role": "CITIZEN", "citizenId": "CITIZEN-API"}))
            first.commit()
            self.assertEqual(get_citizen_application(app_id, {"role": "CITIZEN", "citizenId": "CITIZEN-API"})["eligibility"]["eligible"], True)
        finally:
            first.close()

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

    def test_workflow_boundary_requires_caller_transaction_and_does_not_commit(self):
        app_id = "APP-WORKFLOW-BOUNDARY-TRANSACTION"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT"}))
            setup.commit()
        with Session(engine) as session:
            with self.assertRaises(RuntimeError):
                mutate_workflow_aggregate(app_id, expected_version=1, session=session, status="IN_PROGRESS")
            session.begin()
            result = mutate_workflow_aggregate(app_id, expected_version=1, session=session, status="IN_PROGRESS")
            self.assertTrue(session.in_transaction())
            session.rollback()
        self.assertEqual(get_application(app_id)["status"], "DRAFT")

    def test_workflow_boundary_updates_application_once_with_history_and_refresh(self):
        app_id = "APP-WORKFLOW-BOUNDARY-STATUS"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT", "statusHistory": []}))
            setup.commit()
        APPLICATIONS[app_id] = {"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "STALE_LOCAL"}
        with Session(engine) as session:
            session.begin()
            result = mutate_workflow_aggregate(app_id, expected_version=1, session=session, status="IN_PROGRESS", actor="TEST")
            self.assertEqual(result["application"]["status"], "IN_PROGRESS")
            self.assertEqual(result["application_version"], 2)
            session.commit()
        refreshed = refresh_workflow_aggregate(app_id)
        self.assertEqual(refreshed["application"]["status"], "IN_PROGRESS")
        self.assertEqual(refreshed["application_version"], 2)
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            history = session.query(WorkflowHistoryRow).filter_by(app_id=app_id).all()
            self.assertEqual(row.version, 2)
            self.assertEqual(len(history), 1)
            self.assertEqual(row.payload["statusHistory"][-1]["status"], "IN_PROGRESS")
        self.assertEqual(APPLICATIONS[app_id]["status"], "STALE_LOCAL")

    def test_workflow_boundary_locks_application_before_child_and_mutates_child(self):
        app_id = "APP-WORKFLOW-BOUNDARY-CHILD"
        review_id = "REVIEW-WORKFLOW-BOUNDARY-CHILD"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT"}))
            setup.add(EntityReviewRow(review_id=review_id, app_id=app_id, payload={"reviewId": review_id, "appId": app_id, "decision": "PENDING"}))
            setup.commit()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "FOR UPDATE" in statement.upper():
                statements.append(statement.lower())
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with Session(engine) as session:
                session.begin()
                result = mutate_workflow_aggregate(app_id, expected_version=1, session=session,
                                                   child_kind="entity_review", child_id=review_id,
                                                   child_patch={"decision": "APPROVED"})
                session.commit()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(result["child"]["decision"], "APPROVED")
        self.assertGreaterEqual(len(statements), 2)
        self.assertIn("applications", statements[0])
        self.assertIn("entity_reviews", statements[1])
        self.assertEqual(get_application(app_id)["status"], "DRAFT")

    def test_workflow_boundary_expected_version_race_allows_one_writer(self):
        app_id = "APP-WORKFLOW-BOUNDARY-RACE"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT"}))
            setup.commit()
        first = Session(engine)
        second = Session(engine)
        first.begin()
        second.begin()
        try:
            first_result = mutate_workflow_aggregate(app_id, expected_version=1, session=first, status="IN_PROGRESS")
            first.commit()
            with self.assertRaises(ApplicationConcurrencyError):
                mutate_workflow_aggregate(app_id, expected_version=1, session=second, status="CANCELLED")
            second.rollback()
        finally:
            first.close()
            second.close()
        self.assertEqual(first_result["application"]["status"], "IN_PROGRESS")
        self.assertEqual(get_application(app_id)["status"], "IN_PROGRESS")

    def test_workflow_boundary_rollback_leaves_no_version_or_history_phantom(self):
        app_id = "APP-WORKFLOW-BOUNDARY-ROLLBACK"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT"}))
            setup.commit()
        with Session(engine) as session:
            session.begin()
            mutate_workflow_aggregate(app_id, expected_version=1, session=session, application_patch={"remarks": "temporary"})
            session.rollback()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            self.assertEqual(row.version, 1)
            self.assertNotIn("remarks", row.payload)
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 0)

    def test_workflow_boundary_duplicate_status_retry_is_idempotent(self):
        app_id = "APP-WORKFLOW-BOUNDARY-IDEMPOTENT"
        with Session(engine) as setup:
            setup.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN-BOUNDARY", status="DRAFT", version=1,
                                     payload={"appId": app_id, "citizenId": "CITIZEN-BOUNDARY", "status": "DRAFT", "statusHistory": []}))
            setup.commit()
        with Session(engine) as session:
            session.begin()
            mutate_workflow_aggregate(app_id, expected_version=1, session=session, status="IN_PROGRESS")
            session.commit()
        with Session(engine) as session:
            session.begin()
            result = mutate_workflow_aggregate(app_id, expected_version=2, session=session, status="IN_PROGRESS")
            session.commit()
        self.assertEqual(result["application"]["status"], "IN_PROGRESS")
        with Session(engine) as session:
            self.assertEqual(session.get(ApplicationRow, app_id).version, 2)
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 1)

    def _seed_entity_review_for_migration(self, suffix):
        app_id = f"APP-ENTITY-MIGRATION-{suffix}"
        review_id = f"ER-ENTITY-MIGRATION-{suffix}"
        review = {
            "reviewId": review_id, "appId": app_id, "requirementCode": "IDENTITY",
            "source": "Education Department", "status": "WAITING_FOR_OFFICER", "decision": None,
            "sourceRecordId": "EDU-1", "confidenceScore": 0.78, "confidenceLevel": "MEDIUM",
            "provenance": {"sourceSystem": "Education Department", "sourceRecordId": "EDU-1"},
            "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00",
        }
        app = {
            "appId": app_id, "citizenId": "CITIZEN-ENTITY-MIGRATION", "status": "WAITING_FOR_OFFICER",
            "statusHistory": [], "requirements": [{"code": "IDENTITY", "status": "REVIEW_REQUIRED", "resolution": {}}],
            "entityReviews": [review], "conflictReviews": [], "eligibility": {},
        }
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id=app["citizenId"], status=app["status"], version=1, payload=app))
            session.add(EntityReviewRow(review_id=review_id, app_id=app_id, payload=review))
            session.commit()
        APPLICATIONS[app_id] = dict(app)
        ENTITY_REVIEWS[review_id] = dict(review)
        return app_id, review_id

    def test_entity_review_action_is_postgres_authoritative_and_consistent(self):
        app_id, review_id = self._seed_entity_review_for_migration("SUCCESS")
        event_seen = []
        def observe(event):
            event_seen.append(get_application(app_id)["status"])
        event_bus.subscribe("ENTITY_MATCH_DECIDED", observe)
        try:
            app, review = entity_review_action(review_id, "MATCH", "OFFICER-1", "Confirmed identity")
        finally:
            event_bus._subscribers["ENTITY_MATCH_DECIDED"].remove(observe)
        self.assertEqual(app["status"], "IN_PROGRESS")
        self.assertEqual(review["status"], "APPROVED")
        self.assertEqual(review["decision"], "MATCH")
        self.assertEqual(APPLICATIONS[app_id]["status"], "IN_PROGRESS")
        self.assertEqual(ENTITY_REVIEWS[review_id]["decision"], "MATCH")
        self.assertEqual(event_seen, ["IN_PROGRESS"])
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            persisted_review = session.get(EntityReviewRow, review_id)
            histories = session.query(WorkflowHistoryRow).filter_by(app_id=app_id).all()
            self.assertEqual(row.version, 2)
            self.assertEqual(row.status, "IN_PROGRESS")
            self.assertEqual(persisted_review.payload["decision"], "MATCH")
            requirement = next(item for item in row.payload["requirements"] if item["code"] == "IDENTITY")
            self.assertEqual(requirement["status"], "FOUND")
            self.assertEqual(requirement["resolution"]["decision"], "HUMAN_ACCEPTED")
            self.assertEqual(len(histories), 1)

    def test_entity_review_action_does_not_allow_legacy_snapshot_overwrite(self):
        app_id, review_id = self._seed_entity_review_for_migration("FENCE")
        entity_review_action(review_id, "MATCH", "OFFICER-1", "Confirmed identity")
        with self.assertRaises(ApplicationAuthorityError):
            persist_transition({"appId": app_id, "citizenId": "CITIZEN-ENTITY-MIGRATION", "status": "DRAFT"}, {"status": "DRAFT", "at": "2026-01-01T00:00:00+00:00"})
        APPLICATIONS[app_id]["status"] = "STALE_LOCAL"
        ENTITY_REVIEWS[review_id]["decision"] = "STALE_LOCAL"
        persist_state()
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            review = session.get(EntityReviewRow, review_id)
            self.assertEqual(row.status, "IN_PROGRESS")
            self.assertEqual(review.payload["decision"], "MATCH")

    def test_entity_review_action_same_decision_is_idempotent_without_duplicate_history(self):
        app_id, review_id = self._seed_entity_review_for_migration("IDEMPOTENT")
        first_app, first_review = entity_review_action(review_id, "MATCH", "OFFICER-1", "Confirmed identity")
        second_app, second_review = entity_review_action(review_id, "MATCH", "OFFICER-1", "Confirmed identity again")
        self.assertEqual(first_app["status"], second_app["status"])
        self.assertEqual(first_review["decision"], second_review["decision"])
        with Session(engine) as session:
            self.assertEqual(session.get(ApplicationRow, app_id).version, 2)
            self.assertEqual(session.query(WorkflowHistoryRow).filter_by(app_id=app_id).count(), 1)

    def test_concurrent_entity_review_decisions_serialize_on_application_and_review(self):
        app_id, review_id = self._seed_entity_review_for_migration("RACE")
        barrier = threading.Barrier(2)
        outcomes = []
        def decide(value):
            barrier.wait()
            try:
                result = entity_review_action(review_id, value, "OFFICER-1", f"Decision {value}")
                outcomes.append((value, "ok", result[1]["decision"]))
            except Exception as error:
                outcomes.append((value, type(error).__name__, str(error)))
        first = threading.Thread(target=decide, args=("MATCH",))
        second = threading.Thread(target=decide, args=("REJECT",))
        first.start(); second.start(); first.join(); second.join()
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(sum(item[1] == "ok" for item in outcomes), 1)
        self.assertEqual(sum(item[1] == "ValueError" for item in outcomes), 1)
        with Session(engine) as session:
            row = session.get(ApplicationRow, app_id)
            review = session.get(EntityReviewRow, review_id)
            self.assertEqual(row.version, 2)
            self.assertIn(review.payload["decision"], {"MATCH", "REJECT"})

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


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
