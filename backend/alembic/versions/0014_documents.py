"""Add document/artifact reference table for the document retrieval layer."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_documents"
down_revision = "0013_citizens_req_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(160), primary_key=True),
        # app_id/dependency_id are deliberately NOT foreign keys: dependency (and
        # sometimes application) rows for an in-flight workflow may not yet be
        # durably persisted to PostgreSQL when a document row is written (they
        # live in the process-local workflow dicts until the request-boundary
        # snapshot). This mirrors the existing EventRow/AuditEntryRow convention
        # of unconstrained reference columns for in-flight workflow state.
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.Column("dependency_id", sa.String(160), nullable=True),
        sa.Column("requirement_code", sa.String(120), nullable=False),
        sa.Column("citizen_id", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("provider_id", sa.String(120), sa.ForeignKey("providers.provider_id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reference_uri", sa.String(300), nullable=True),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_documents_app_id", "documents", ["app_id"])
    op.create_index("ix_documents_dependency_id", "documents", ["dependency_id"])
    op.create_index("ix_documents_requirement_code", "documents", ["requirement_code"])
    op.create_index("ix_documents_citizen_id", "documents", ["citizen_id"])
    op.create_index("ix_documents_source_type", "documents", ["source_type"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_provider_id", "documents", ["provider_id"])


def downgrade():
    op.drop_index("ix_documents_provider_id", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_source_type", table_name="documents")
    op.drop_index("ix_documents_citizen_id", table_name="documents")
    op.drop_index("ix_documents_requirement_code", table_name="documents")
    op.drop_index("ix_documents_dependency_id", table_name="documents")
    op.drop_index("ix_documents_app_id", table_name="documents")
    op.drop_table("documents")
