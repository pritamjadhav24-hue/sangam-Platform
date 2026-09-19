"""Add explicit provider capability relationships."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_provider_capabilities"
down_revision = "62ebc0864a84"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_capabilities",
        sa.Column("capability_id", sa.String(160), primary_key=True),
        sa.Column("provider_id", sa.String(120), sa.ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(120), nullable=False),
        sa.Column("service_id", sa.String(120), sa.ForeignKey("service_catalog.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_provider_capabilities_provider_id", "provider_capabilities", ["provider_id"])
    op.create_index("ix_provider_capabilities_capability_code", "provider_capabilities", ["capability_code"])
    op.create_index("ix_provider_capabilities_service_id", "provider_capabilities", ["service_id"])


def downgrade():
    op.drop_index("ix_provider_capabilities_service_id", table_name="provider_capabilities")
    op.drop_index("ix_provider_capabilities_capability_code", table_name="provider_capabilities")
    op.drop_index("ix_provider_capabilities_provider_id", table_name="provider_capabilities")
    op.drop_table("provider_capabilities")
