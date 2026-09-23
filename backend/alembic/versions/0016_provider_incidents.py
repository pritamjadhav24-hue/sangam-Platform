"""Add provider incidents table (Admin Console provider-outage model).

A provider incident is a system/provider-level record: one incident
represents one underlying department/provider outage or degradation,
distinct from the many individual ProviderJobRow/DependencyRow executions
it may affect. Detection reuses the existing integration_health() health
-change tracking (app.engine.adapters._last_health) -- this migration only
adds somewhere durable to record the transition, it does not change how a
health change is detected.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_provider_incidents"
down_revision = "0015_citizen_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_incidents",
        sa.Column("incident_id", sa.String(160), primary_key=True),
        sa.Column("provider_system", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_provider_incidents_provider_system", "provider_incidents", ["provider_system"])
    op.create_index("ix_provider_incidents_status", "provider_incidents", ["status"])


def downgrade():
    op.drop_index("ix_provider_incidents_status", table_name="provider_incidents")
    op.drop_index("ix_provider_incidents_provider_system", table_name="provider_incidents")
    op.drop_table("provider_incidents")
