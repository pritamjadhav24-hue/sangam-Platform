"""Deterministic reset for the intentionally in-memory SIH demo."""

import itertools

from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.core.notification_manager import notification_manager
from app.engine import adapters, consent_manager, dependency_orchestrator, semantic_mapper, workflow_engine
from app.mocks import education_dept, revenue_dept
from app.mocks.identity_provider import SESSIONS


def reset_demo_state() -> None:
    """Return every mutable demo store and deterministic counter to its clean state."""
    workflow_engine.APPLICATIONS.clear()
    workflow_engine.DEPENDENCIES.clear()
    workflow_engine.ENTITY_REVIEWS.clear()
    workflow_engine.CONFLICT_REVIEWS.clear()
    workflow_engine._counter = itertools.count(142)
    workflow_engine._review_counter = itertools.count(1)
    workflow_engine._conflict_counter = itertools.count(1)

    dependency_orchestrator._dependency_counter = itertools.count(1)
    consent_manager.CONSENTS.clear()
    notification_manager.notifications.clear()
    notification_manager._processed_event_ids.clear()
    notification_manager._counter = itertools.count(1)
    event_bus.reset()
    audit_bus.reset()
    SESSIONS.clear()

    adapters._availability.clear()
    adapters._last_health.clear()
    adapters._runtime_health.clear()
    revenue_dept.DOMICILE_RECORD = None
    education_dept.set_income_conflict(False)
    semantic_mapper.reset_mapping_state()
