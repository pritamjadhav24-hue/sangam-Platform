"""Citizen application Review -> Submit for Phase 6B/6C/6D authoritative
applications (Phase 6E).

Reuses every existing primitive unchanged:

- "Is a requirement satisfied?" reuses requirement_fulfillment.SUCCESS_STATUSES
  (VALIDATED/RETRIEVED) -- the exact same canonical completion rule Auto-Fill
  and manual upload already use, not a second definition of "done".
- The actual status transition reuses persistence.transition_application_status,
  the same caller-owned-transaction, row-locked, version-checked, CANONICAL_
  STATUSES/VALID_TRANSITIONS-governed gateway Phase 6 already uses elsewhere
  (e.g. entity_review_action). IN_PROGRESS -> SUBMITTED is already a valid
  transition in workflow_engine.VALID_TRANSITIONS; nothing here redefines the
  workflow state machine.
- Requirement mutation (Auto-Fill, manual upload, reject) is blocked once an
  application is SUBMITTED by a single guard inside requirement_fulfillment.
  mutate_requirement_under_lock -- the same row lock that already serializes
  concurrent requirement writes also serializes against a concurrent
  submission, so this needs no new locking mechanism.

submit_application() is idempotent by construction: transition_application_
status() already treats "already at the target status" as a no-op success
(status not in VALID_TRANSITIONS is only checked when the status actually
differs), so a repeated or concurrently-racing submit request safely returns
the existing SUBMITTED state instead of raising or duplicating any side
effect. The row lock it acquires (SELECT ... FOR UPDATE) also means two
truly concurrent submit calls serialize: the second one blocks until the
first commits, then observes the application is already SUBMITTED and
returns the same idempotent result.
"""
from __future__ import annotations

from typing import Optional

from app.engine.requirement_fulfillment import SUCCESS_STATUSES

SUBMITTABLE_STATUS = "IN_PROGRESS"
SUBMITTED_STATUS = "SUBMITTED"


class ApplicationAlreadySubmittedError(RuntimeError):
    """Raised only when a caller needs to distinguish "already submitted"
    from a genuine readiness failure; submit_application itself treats this
    as a successful idempotent no-op rather than raising it."""


class ApplicationNotSubmittableError(RuntimeError):
    """The application is in a status Phase 6E's submission flow does not
    apply to (e.g. already cancelled/rejected by some other path)."""


class SubmissionNotReadyError(ValueError):
    def __init__(self, blocking_codes: list[str]):
        self.blocking_codes = blocking_codes
        super().__init__(f"Application is not ready for submission: {', '.join(blocking_codes)}")


def evaluate_submission_readiness(application: dict) -> dict:
    """Pure, read-only readiness check against the authoritative requirement
    list. A requirement blocks submission when it is mandatory (the existing
    per-requirement 'mandatory' flag, defaulting to True for any requirement
    that doesn't carry one) and its status is not one of the existing
    canonical success statuses. This treats an unrecognised/malformed status
    value as blocking (fail closed) rather than assuming it means success.
    """
    blocking_codes = []
    for requirement in application.get("requirements", []):
        if requirement.get("mandatory", True) is False:
            continue
        if requirement.get("status") not in SUCCESS_STATUSES:
            blocking_codes.append(requirement.get("code"))
    return {"ready": not blocking_codes, "blockingCodes": blocking_codes}


def submit_application(application_id: str, citizen_id: str) -> dict:
    """Evaluate readiness and transition IN_PROGRESS -> SUBMITTED atomically
    under one row lock, so a requirement cannot finish (or be manually
    uploaded) *during* the readiness check and be missed, and two concurrent
    submissions cannot both succeed as independent events.

    Raises KeyError if the application does not exist,
    PermissionError if ``citizen_id`` does not own it,
    ApplicationNotSubmittableError if its status is neither IN_PROGRESS nor
    already SUBMITTED, and SubmissionNotReadyError (carrying the blocking
    requirement codes) if it is not yet ready. Returns the resulting
    application either way it succeeds -- including the idempotent case
    where it was already SUBMITTED.
    """
    from sqlalchemy.orm import Session
    from app.core.persistence import engine, get_application, transition_application_status

    with Session(engine) as session:
        locked = get_application(application_id, for_update=True, session=session)
        if locked is None:
            raise KeyError(application_id)
        if locked.get("citizenId") != citizen_id:
            raise PermissionError(application_id)
        status = locked.get("status")
        if status == SUBMITTED_STATUS:
            session.commit()
            return locked
        if status != SUBMITTABLE_STATUS:
            session.commit()
            raise ApplicationNotSubmittableError(status)
        readiness = evaluate_submission_readiness(locked)
        if not readiness["ready"]:
            session.commit()
            raise SubmissionNotReadyError(readiness["blockingCodes"])
        updated = transition_application_status(
            application_id, SUBMITTED_STATUS, actor=citizen_id, source="citizen_routes", session=session,
        )
        session.commit()
        return updated
