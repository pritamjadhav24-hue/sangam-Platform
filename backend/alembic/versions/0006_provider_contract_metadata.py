"""Add explicit provider contract and environment metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0006_provider_contract_metadata"
down_revision = "0005_operational_observability"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("providers", sa.Column("contract_version", sa.String(40), nullable=False, server_default="v1"))
    op.add_column("providers", sa.Column("environment", sa.String(20), nullable=False, server_default="SANDBOX"))
    op.add_column("providers", sa.Column("auth_type", sa.String(40), nullable=False, server_default="NONE"))
    op.add_column("providers", sa.Column("endpoint_ref", sa.String(200), nullable=True))
    op.add_column("providers", sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("providers", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))


def downgrade():
    for column in ("max_attempts", "timeout_seconds", "endpoint_ref", "auth_type", "environment", "contract_version"):
        op.drop_column("providers", column)
