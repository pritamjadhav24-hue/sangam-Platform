"""Add PostgreSQL-owned worker execution leases."""
from alembic import op
import sqlalchemy as sa

revision = "0008_worker_leases"
down_revision = "0007_job_dispatch"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("provider_jobs", sa.Column("lease_owner", sa.String(160), nullable=True))
    op.add_column("provider_jobs", sa.Column("lease_until", sa.String(64), nullable=True))
    op.create_index("ix_provider_jobs_lease_owner", "provider_jobs", ["lease_owner"])
    op.create_index("ix_provider_jobs_lease_until", "provider_jobs", ["lease_until"])


def downgrade():
    op.drop_index("ix_provider_jobs_lease_until", table_name="provider_jobs")
    op.drop_index("ix_provider_jobs_lease_owner", table_name="provider_jobs")
    op.drop_column("provider_jobs", "lease_until")
    op.drop_column("provider_jobs", "lease_owner")
