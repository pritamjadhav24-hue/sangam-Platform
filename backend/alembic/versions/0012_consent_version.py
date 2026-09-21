"""Add optimistic-concurrency metadata to consent rows."""

from alembic import op
import sqlalchemy as sa


revision = "0012_consent_version"
down_revision = "0011_app_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("consents", sa.Column("version", sa.BigInteger(), nullable=True))
    op.execute(sa.text("UPDATE consents SET version = 1 WHERE version IS NULL"))
    op.alter_column(
        "consents",
        "version",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("1"),
    )


def downgrade() -> None:
    op.drop_column("consents", "version")
