"""Test-only helper: remove ProviderIncidentRow records a test created, so
simulated health transitions never leave fake incidents in the shared
development database that the Admin console reads."""
from datetime import datetime, timezone

from app.core.persistence import ProviderIncidentRow, Session, engine


def now() -> datetime:
    return datetime.now(timezone.utc)


def purge_incidents_since(provider_system: str, since: datetime) -> None:
    with Session(engine) as session:
        session.query(ProviderIncidentRow).filter(
            ProviderIncidentRow.provider_system == provider_system,
            ProviderIncidentRow.detected_at >= since,
        ).delete(synchronize_session=False)
        session.commit()
