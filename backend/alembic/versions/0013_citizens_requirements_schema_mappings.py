"""Add platform citizen registry, canonical requirement catalog, and schema mappings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_citizens_req_schema"
down_revision = "0012_consent_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "citizens",
        sa.Column("citizen_id", sa.String(120), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("date_of_birth", sa.String(20), nullable=False),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("persona", sa.String(60), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_citizens_phone", "citizens", ["phone"])
    op.create_index("ix_citizens_district", "citizens", ["district"])
    op.create_index("ix_citizens_persona", "citizens", ["persona"])

    op.create_table(
        "requirements",
        sa.Column("requirement_code", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("data_type", sa.String(40), nullable=False, server_default="DOCUMENT"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_requirements_category", "requirements", ["category"])

    op.create_table(
        "schema_mappings",
        sa.Column("mapping_id", sa.String(160), primary_key=True),
        sa.Column("provider_id", sa.String(120), sa.ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.String(120), sa.ForeignKey("service_catalog.service_id", ondelete="CASCADE"), nullable=True),
        sa.Column("department_field", sa.String(200), nullable=False),
        sa.Column("canonical_field", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(40), nullable=False, server_default="string"),
        sa.Column("transform", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("provider_id", "department_field", name="uq_schema_mappings_provider_field"),
    )
    op.create_index("ix_schema_mappings_provider_id", "schema_mappings", ["provider_id"])
    op.create_index("ix_schema_mappings_service_id", "schema_mappings", ["service_id"])
    op.create_index("ix_schema_mappings_canonical_field", "schema_mappings", ["canonical_field"])


def downgrade():
    op.drop_index("ix_schema_mappings_canonical_field", table_name="schema_mappings")
    op.drop_index("ix_schema_mappings_service_id", table_name="schema_mappings")
    op.drop_index("ix_schema_mappings_provider_id", table_name="schema_mappings")
    op.drop_table("schema_mappings")

    op.drop_index("ix_requirements_category", table_name="requirements")
    op.drop_table("requirements")

    op.drop_index("ix_citizens_persona", table_name="citizens")
    op.drop_index("ix_citizens_district", table_name="citizens")
    op.drop_index("ix_citizens_phone", table_name="citizens")
    op.drop_table("citizens")
