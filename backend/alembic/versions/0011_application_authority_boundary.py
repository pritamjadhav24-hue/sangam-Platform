"""Add the PostgreSQL application authority boundary marker."""

from alembic import op
import sqlalchemy as sa


revision = "0011_app_authority"
down_revision = "0010_workflow_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("authoritative_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_applications_authoritative_at",
        "applications",
        ["authoritative_at"],
        postgresql_where=sa.text("authoritative_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_applications_authoritative_at", table_name="applications")
    op.drop_column("applications", "authoritative_at")
