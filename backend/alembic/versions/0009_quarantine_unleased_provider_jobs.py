"""Quarantine pre-lease RUNNING provider jobs instead of guessing ownership."""

from alembic import op


revision = "0009_quarantine_unleased"
down_revision = "0008_worker_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE provider_jobs
        SET status = 'DEAD_LETTER',
            error_category = 'MIGRATION_RECOVERY_REQUIRED',
            error_message = 'RUNNING job had no worker lease; manual replay is required.'
        WHERE status = 'RUNNING'
          AND lease_owner IS NULL
          AND lease_until IS NULL
        """
    )


def downgrade():
    # The prior RUNNING state and ownership cannot be reconstructed safely.
    pass
