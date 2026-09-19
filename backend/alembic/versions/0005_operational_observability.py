"""Add safe worker heartbeat state for operational readiness."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_operational_observability"
down_revision = "0004_provider_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(160), primary_key=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("last_seen", sa.String(64), nullable=False),
        sa.Column("current_job_id", sa.String(180), nullable=True),
        sa.Column("redis_status", sa.String(40), nullable=False),
        sa.Column("postgres_status", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_worker_heartbeats_last_seen", "worker_heartbeats", ["last_seen"])


def downgrade():
    op.drop_index("ix_worker_heartbeats_last_seen", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
