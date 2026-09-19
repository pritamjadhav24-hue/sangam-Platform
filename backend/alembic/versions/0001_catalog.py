"""Add database-owned organization and service catalog."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("departments", sa.Column("department_id", sa.String(120), primary_key=True), sa.Column("name", sa.String(200), nullable=False, unique=True), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_table("providers", sa.Column("provider_id", sa.String(120), primary_key=True), sa.Column("department_id", sa.String(120), sa.ForeignKey("departments.department_id"), nullable=False), sa.Column("name", sa.String(200), nullable=False, unique=True), sa.Column("adapter_type", sa.String(120), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_table("service_catalog", sa.Column("service_id", sa.String(120), primary_key=True), sa.Column("provider_id", sa.String(120), sa.ForeignKey("providers.provider_id"), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("requirement_code", sa.String(120), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_table("scheme_catalog", sa.Column("scheme_id", sa.String(120), primary_key=True), sa.Column("name", sa.String(240), nullable=False), sa.Column("department", sa.String(200), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("payload", postgresql.JSONB(), nullable=False))
    op.create_table("scheme_requirements", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("scheme_id", sa.String(120), sa.ForeignKey("scheme_catalog.scheme_id", ondelete="CASCADE"), nullable=False), sa.Column("requirement_code", sa.String(120), nullable=False), sa.Column("label", sa.String(200), nullable=False), sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("payload", postgresql.JSONB(), nullable=False))


def downgrade():
    op.drop_table("scheme_requirements")
    op.drop_table("scheme_catalog")
    op.drop_table("service_catalog")
    op.drop_table("providers")
    op.drop_table("departments")
