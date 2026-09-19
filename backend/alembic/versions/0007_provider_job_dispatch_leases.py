"""Add bounded PostgreSQL-to-Redis dispatch leases."""
from alembic import op
import sqlalchemy as sa

revision = "0007_job_dispatch"
down_revision = "0006_provider_contract_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("provider_jobs", sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("provider_jobs", sa.Column("last_dispatched_at", sa.String(64), nullable=True))
    op.add_column("provider_jobs", sa.Column("dispatch_claimed_until", sa.String(64), nullable=True))
    op.create_index("ix_provider_jobs_dispatch_claimed_until", "provider_jobs", ["dispatch_claimed_until"])


def downgrade():
    op.drop_index("ix_provider_jobs_dispatch_claimed_until", table_name="provider_jobs")
    op.drop_column("provider_jobs", "dispatch_claimed_until")
    op.drop_column("provider_jobs", "last_dispatched_at")
    op.drop_column("provider_jobs", "dispatch_attempts")
