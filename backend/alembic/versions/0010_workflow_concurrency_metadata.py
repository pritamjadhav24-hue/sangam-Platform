"""Add typed workflow concurrency metadata without changing workflow writers."""

from alembic import op
import sqlalchemy as sa


revision = "0010_workflow_metadata"
down_revision = "0009_quarantine_unleased"
branch_labels = None
depends_on = None


def _validate_timestamps(bind, table_name):
    bind.exec_driver_sql(
        f"""
        DO $$
        DECLARE item RECORD;
                parsed timestamptz;
        BEGIN
            FOR item IN
                SELECT {"app_id" if table_name == "applications" else "dependency_id"} AS record_id,
                       key_name,
                       value_text
                FROM {table_name},
                     LATERAL (VALUES
                         ('createdAt', payload->>'createdAt'),
                         ('updatedAt', payload->>'updatedAt')
                     ) AS values_table(key_name, value_text)
                WHERE payload ? key_name
            LOOP
                IF item.value_text IS NULL OR btrim(item.value_text) = '' THEN
                    RAISE EXCEPTION '0010 invalid %% timestamp for %%: value is empty', item.key_name, item.record_id;
                END IF;
                BEGIN
                    parsed := item.value_text::timestamptz;
                EXCEPTION WHEN others THEN
                    RAISE EXCEPTION '0010 invalid %% timestamp for %%: %%', item.key_name, item.record_id, item.value_text;
                END;
            END LOOP;
        END $$;
        """
    )


def _validate_retry_values(bind):
    bind.exec_driver_sql(
        """
        DO $$
        DECLARE item RECORD;
        BEGIN
            FOR item IN
                SELECT dependency_id, key_name, value_text
                FROM dependencies,
                     LATERAL (VALUES
                         ('attempts', payload->>'attempts'),
                         ('maxAttempts', payload->>'maxAttempts')
                     ) AS values_table(key_name, value_text)
                WHERE payload ? key_name
                  AND value_text IS NOT NULL
            LOOP
                BEGIN
                    IF item.value_text !~ '^[0-9]+$' THEN
                        RAISE EXCEPTION 'not an integer';
                    END IF;
                    IF item.key_name = 'attempts' AND item.value_text::integer < 0 THEN
                        RAISE EXCEPTION 'negative attempts';
                    END IF;
                    IF item.key_name = 'maxAttempts' AND item.value_text::integer < 1 THEN
                        RAISE EXCEPTION 'maxAttempts must be at least 1';
                    END IF;
                EXCEPTION WHEN others THEN
                    RAISE EXCEPTION '0010 invalid %% for dependency %%: %%', item.key_name, item.dependency_id, item.value_text;
                END;
            END LOOP;
        END $$;
        """
    )


def _validate_required_data(bind):
    bind.exec_driver_sql(
        """
        DO $$
        DECLARE item RECORD;
        BEGIN
            FOR item IN
                SELECT dependency_id
                FROM dependencies
                WHERE NOT (payload ? 'requiredData')
                   OR jsonb_typeof(payload->'requiredData') <> 'string'
                   OR btrim(payload->>'requiredData') = ''
            LOOP
                RAISE EXCEPTION '0010 invalid requiredData for dependency %%', item.dependency_id;
            END LOOP;
        END $$;
        """
    )


def _validate_existing_payloads(bind):
    """Validate legacy JSONB before any typed-column cast or normalization."""
    _validate_timestamps(bind, "applications")
    _validate_timestamps(bind, "dependencies")
    _validate_required_data(bind)
    _validate_retry_values(bind)


def _backfill_existing_rows(bind):
    """Copy validated legacy JSONB values without changing the source payload."""
    bind.exec_driver_sql(
        """
        UPDATE applications
        SET created_at = NULLIF(payload->>'createdAt', '')::timestamptz,
            updated_at = NULLIF(payload->>'updatedAt', '')::timestamptz
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE dependencies
        SET created_at = NULLIF(payload->>'createdAt', '')::timestamptz,
            updated_at = NULLIF(payload->>'updatedAt', '')::timestamptz,
            required_data = payload->>'requiredData',
            job_id = payload->>'jobId',
            job_status = payload->>'jobStatus',
            result_reference = payload->>'resultReference',
            attempts = COALESCE((payload->>'attempts')::integer, 0),
            max_attempts = COALESCE((payload->>'maxAttempts')::integer, 3)
        """
    )


def upgrade():
    op.add_column("applications", sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"))
    op.add_column("applications", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("dependencies", sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"))
    op.add_column("dependencies", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dependencies", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dependencies", sa.Column("required_data", sa.Text(), nullable=True))
    op.add_column("dependencies", sa.Column("job_id", sa.Text(), nullable=True))
    op.add_column("dependencies", sa.Column("job_status", sa.Text(), nullable=True))
    op.add_column("dependencies", sa.Column("result_reference", sa.Text(), nullable=True))
    op.add_column("dependencies", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("dependencies", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))

    bind = op.get_bind()
    _validate_existing_payloads(bind)
    _backfill_existing_rows(bind)

    op.create_index("ix_dependencies_app_id_required_data", "dependencies", ["app_id", "required_data"])
    op.create_index("ix_dependencies_job_id", "dependencies", ["job_id"])


def downgrade():
    op.drop_index("ix_dependencies_job_id", table_name="dependencies")
    op.drop_index("ix_dependencies_app_id_required_data", table_name="dependencies")
    op.drop_column("dependencies", "max_attempts")
    op.drop_column("dependencies", "attempts")
    op.drop_column("dependencies", "result_reference")
    op.drop_column("dependencies", "job_status")
    op.drop_column("dependencies", "job_id")
    op.drop_column("dependencies", "required_data")
    op.drop_column("dependencies", "updated_at")
    op.drop_column("dependencies", "created_at")
    op.drop_column("dependencies", "version")
    op.drop_column("applications", "updated_at")
    op.drop_column("applications", "created_at")
    op.drop_column("applications", "version")
