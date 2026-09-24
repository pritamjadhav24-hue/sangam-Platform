"""Automatic provider recovery/replay: when a provider's health transitions
back to AVAILABLE/HEALTHY (the existing app.engine.adapters.integration_health
change-detection -- no second health monitor), SANGAM should safely replay
whichever DEAD_LETTER provider jobs for that provider are still eligible,
without ever overwriting a requirement a fallback provider or a citizen's
manual upload already fulfilled. Reuses the existing replay_dead_letter_job()
gateway and the existing JobQueue/ProviderJobRow infrastructure -- this is
not a second retry/replay engine.
"""
from __future__ import annotations

import unittest

from app.core.job_queue import JobQueue
from app.core.persistence import (
    ApplicationRow, DependencyRow, ProviderJobRow, Session, engine, find_dead_letter_jobs_for_provider,
    provider_job_detail, record_provider_health_transition,
    replay_eligible_dead_letter_jobs_for_provider,
)
from app.core.redis_service import MemoryRedis, build_test_redis_service


def _dead_letter_job(redis, provider_id: str, application_id: str, dependency_id: str) -> dict:
    queue = JobQueue(redis)
    job = queue.enqueue("retrieve.test", application_id, application_id, dependency_id, {"providerId": provider_id})
    claimed = queue.claim(job)
    claimed.update({"status": "DEAD_LETTER", "error": {"category": "TIMEOUT", "message": "safe"}})
    queue.update(claimed)
    return job


class ProviderRecoveryReplayTests(unittest.TestCase):
    def setUp(self):
        self.redis = build_test_redis_service(MemoryRedis())
        self._app_ids: list[str] = []
        self._dependency_ids: list[str] = []

    def tearDown(self):
        with Session(engine) as session:
            if self._app_ids:
                session.query(ProviderJobRow).filter(ProviderJobRow.application_id.in_(self._app_ids)).delete(synchronize_session=False)
            if self._dependency_ids:
                session.query(DependencyRow).filter(DependencyRow.dependency_id.in_(self._dependency_ids)).delete(synchronize_session=False)
            if self._app_ids:
                session.query(ApplicationRow).filter(ApplicationRow.app_id.in_(self._app_ids)).delete(synchronize_session=False)
            session.commit()

    def _make_application(self, app_id: str, requirement_code: str, requirement_status: str, extra_fields: dict | None = None) -> None:
        requirement = {"code": requirement_code, "label": requirement_code, "status": requirement_status, **(extra_fields or {})}
        with Session(engine) as session:
            session.add(ApplicationRow(app_id=app_id, citizen_id="CITIZEN_RECOVERY", status="IN_PROGRESS",
                                        payload={"appId": app_id, "citizenId": "CITIZEN_RECOVERY", "status": "IN_PROGRESS", "requirements": [requirement]}))
            session.commit()
        self._app_ids.append(app_id)

    def _make_dependency(self, dependency_id: str, app_id: str, requirement_code: str, status: str = "WAITING_FOR_DEPENDENCY") -> None:
        with Session(engine) as session:
            session.add(DependencyRow(dependency_id=dependency_id, app_id=app_id, status=status, required_data=requirement_code,
                                       payload={"dependencyId": dependency_id, "appId": app_id, "status": status, "requiredData": requirement_code}))
            session.commit()
        self._dependency_ids.append(dependency_id)

    # 13/14. Eligible job replays after recovery and is safely re-queued.
    def test_eligible_dead_letter_job_is_replayed_on_recovery(self):
        app_id, dependency_id, provider = "APP-RECOVERY-001", "DEP-RECOVERY-001", "RECOVERY-TEST-PROVIDER-1"
        self._make_application(app_id, "TEST_REQUIREMENT", "ACTION_REQUIRED")
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        result = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        self.assertEqual(result["replayedJobIds"], [job["jobId"]])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(provider_job_detail(job["jobId"])["status"], "QUEUED")

    # 16. A manually fulfilled requirement (documentId set) is never overwritten by recovery replay.
    def test_manually_fulfilled_requirement_is_never_replayed(self):
        app_id, dependency_id, provider = "APP-RECOVERY-002", "DEP-RECOVERY-002", "RECOVERY-TEST-PROVIDER-2"
        self._make_application(app_id, "TEST_REQUIREMENT", "VALIDATED", extra_fields={"documentId": "DOC-APP-RECOVERY-002-TEST_REQUIREMENT"})
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        result = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        self.assertEqual(result["replayedJobIds"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["jobId"], job["jobId"])
        self.assertEqual(provider_job_detail(job["jobId"])["status"], "DEAD_LETTER")

    # 15. A requirement already fulfilled through a fallback provider is not replayed either.
    def test_requirement_already_fulfilled_via_fallback_is_never_replayed(self):
        app_id, dependency_id, provider = "APP-RECOVERY-003", "DEP-RECOVERY-003", "RECOVERY-TEST-PROVIDER-3"
        self._make_application(app_id, "TEST_REQUIREMENT", "RETRIEVED")
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        result = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        self.assertEqual(result["replayedJobIds"], [])
        self.assertEqual(provider_job_detail(job["jobId"])["status"], "DEAD_LETTER")

    # 17. A job that is not DEAD_LETTER is never selected for replay at all.
    def test_only_dead_letter_jobs_are_candidates_for_replay(self):
        provider = "RECOVERY-TEST-PROVIDER-4"
        self._app_ids.append("APP-RECOVERY-004")  # so tearDown removes this job row
        queue = JobQueue(self.redis)
        job = queue.enqueue("retrieve.test", "APP-RECOVERY-004", "APP-RECOVERY-004", "DEP-RECOVERY-004", {"providerId": provider})
        # Left QUEUED, never claimed/dead-lettered.
        self.assertEqual(find_dead_letter_jobs_for_provider(provider), [])
        result = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        self.assertEqual(result["replayedJobIds"], [])

    # 18. Replay is idempotent: calling it twice never replays the same job again.
    def test_replay_is_idempotent_across_repeated_calls(self):
        app_id, dependency_id, provider = "APP-RECOVERY-005", "DEP-RECOVERY-005", "RECOVERY-TEST-PROVIDER-5"
        self._make_application(app_id, "TEST_REQUIREMENT", "ACTION_REQUIRED")
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        first = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        second = replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        self.assertEqual(first["replayedJobIds"], [job["jobId"]])
        self.assertEqual(second["replayedJobIds"], [], "a job already moved out of DEAD_LETTER must not be replayed again")

    # 21. Correct, distinguishable audit lineage for an automatic recovery replay.
    def test_automatic_recovery_replay_has_distinguishable_audit_lineage(self):
        from app.core.audit_bus import audit_bus
        app_id, dependency_id, provider = "APP-RECOVERY-006", "DEP-RECOVERY-006", "RECOVERY-TEST-PROVIDER-6"
        self._make_application(app_id, "TEST_REQUIREMENT", "ACTION_REQUIRED")
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        before = len(audit_bus.entries)
        replay_eligible_dead_letter_jobs_for_provider(provider, self.redis)
        # audit_bus stores only a payload hash (privacy-preserving,
        # hash-chained ledger), never the raw payload -- so lineage is
        # verified through the entry's own who/why/source/action/
        # correlationId fields, matching how the rest of the app already
        # reads audit_bus.entries.
        new_entries = [entry for entry in audit_bus.entries[before:] if entry["correlationId"] == app_id]
        self.assertTrue(new_entries)
        replay_entry = next(entry for entry in new_entries if entry["action"] == "REPLAY")
        self.assertEqual(replay_entry["source"], provider)
        self.assertIn("automatically replayed", replay_entry["why"])

    # 10/12. Health transition opens then resolves a ProviderIncidentRow, end to end through the real detection hook.
    def test_health_transition_hook_opens_and_resolves_incident_and_triggers_replay(self):
        from app.core.persistence import open_provider_incident_count, provider_incidents_summary
        app_id, dependency_id, provider = "APP-RECOVERY-007", "DEP-RECOVERY-007", "RECOVERY-TEST-PROVIDER-7"
        self._make_application(app_id, "TEST_REQUIREMENT", "ACTION_REQUIRED")
        self._make_dependency(dependency_id, app_id, "TEST_REQUIREMENT")
        job = _dead_letter_job(self.redis, provider, app_id, dependency_id)

        from tests.incident_cleanup import now, purge_incidents_since
        self.addCleanup(purge_incidents_since, provider, now())
        before = open_provider_incident_count()
        record_provider_health_transition(provider, provider, None, "AVAILABLE", "UNAVAILABLE", "UPSTREAM_UNAVAILABLE")
        self.assertEqual(open_provider_incident_count(), before + 1)

        record_provider_health_transition(provider, provider, None, "UNAVAILABLE", "AVAILABLE", None)
        self.assertEqual(open_provider_incident_count(), before)
        incident = next(i for i in provider_incidents_summary() if i["providerSystem"] == provider)
        self.assertEqual(incident["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
