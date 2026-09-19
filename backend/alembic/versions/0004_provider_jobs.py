"""Add durable provider operation jobs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_provider_jobs"
down_revision = "0003_provider_capabilities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_jobs",
        sa.Column("job_id", sa.String(180), primary_key=True),
        sa.Column("job_type", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("application_id", sa.String(120), nullable=True),
        sa.Column("dependency_id", sa.String(160), nullable=True),
        sa.Column("provider_id", sa.String(120), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("started_at", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.String(64), nullable=True),
        sa.Column("error_category", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    for column in ("job_type", "status", "correlation_id", "application_id", "dependency_id", "provider_id"):
        op.create_index(f"ix_provider_jobs_{column}", "provider_jobs", [column])


def downgrade():
    for column in ("provider_id", "dependency_id", "application_id", "correlation_id", "status", "job_type"):
        op.drop_index(f"ix_provider_jobs_{column}", table_name="provider_jobs")
    op.drop_table("provider_jobs")
