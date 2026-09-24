"""Tests for the SANGAM-side database foundation: citizens, requirements,
and schema_mappings. These are additive reference/master-data tables and must
not disturb the existing authoritative workflow tables or their fencing.
"""
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.persistence import (
    REQUIREMENT_CATALOG, CitizenRow, ProviderRow, RequirementCatalogRow, SchemaMappingRow, ServiceCatalogRow,
    citizens_seeded, engine, initialize, requirement_catalog_seeded, seed_catalog, seed_platform_citizens,
    seed_requirement_catalog, seed_schema_mappings,
)
from app.seeds.synthetic_identity_pool import generate_citizen_pool
from tests.catalog_fixture import restore_tables, snapshot_tables


class DatabaseFoundationTests(unittest.TestCase):
    """The seeding tests need these reference tables empty, but they share the
    development database with the running demo -- so the original rows are
    snapshotted first and restored exactly afterwards."""

    def setUp(self):
        initialize()
        self._snapshot = snapshot_tables(RequirementCatalogRow, CitizenRow, SchemaMappingRow)
        self.addCleanup(restore_tables, self._snapshot)
        with Session(engine) as session:
            for model in (RequirementCatalogRow, CitizenRow, SchemaMappingRow):
                session.execute(model.__table__.delete())
            session.commit()

    def test_new_tables_exist(self):
        tables = set(inspect(engine).get_table_names())
        self.assertTrue({"citizens", "requirements", "schema_mappings"}.issubset(tables))

    def test_requirement_catalog_seeding_is_gated_and_idempotent(self):
        with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "false"}):
            seed_requirement_catalog()
        self.assertFalse(requirement_catalog_seeded())

        with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
            seed_requirement_catalog()
            seed_requirement_catalog()  # idempotent: no duplicate-key error, no row growth
        with Session(engine) as session:
            count = session.query(RequirementCatalogRow).filter(
                RequirementCatalogRow.requirement_code.in_([item["code"] for item in REQUIREMENT_CATALOG])
            ).count()
        self.assertEqual(count, len(REQUIREMENT_CATALOG))

    def test_platform_citizens_seeding_is_gated_and_deterministic(self):
        with patch.dict("os.environ", {"SANGAM_SEED_SYNTHETIC_DATA": "false"}):
            seed_platform_citizens()
        self.assertFalse(citizens_seeded())

        with patch.dict("os.environ", {"SANGAM_SEED_SYNTHETIC_DATA": "true"}):
            seed_platform_citizens()
        pool = generate_citizen_pool()
        with Session(engine) as session:
            rows = session.query(CitizenRow).filter(CitizenRow.citizen_id.like("SYN-CIT-%")).all()
        self.assertEqual(len(rows), len(pool))
        self.assertEqual({row.citizen_id for row in rows}, {citizen["citizenId"] for citizen in pool})
        self.assertTrue(all(row.is_synthetic for row in rows))

    def test_generator_is_deterministic_across_calls(self):
        first = generate_citizen_pool(30)
        second = generate_citizen_pool(30)
        self.assertEqual(first, second)

    def test_schema_mappings_reference_only_existing_providers(self):
        with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
            seed_catalog()
            seed_schema_mappings()
        with Session(engine) as session:
            mappings = session.query(SchemaMappingRow).all()
            provider_ids = {row.provider_id for row in session.query(ProviderRow.provider_id).all()}
        self.assertTrue(mappings, "expected at least one seeded schema mapping")
        self.assertTrue(all(mapping.provider_id in provider_ids for mapping in mappings))

    def test_existing_catalog_seed_is_unaffected(self):
        """Guard against the new seed functions changing the pre-existing catalog shape."""
        with patch.dict("os.environ", {"SANGAM_SEED_CATALOG": "true"}):
            seed_catalog()
        with Session(engine) as session:
            services = session.query(ServiceCatalogRow).count()
        self.assertGreaterEqual(services, 5)


if __name__ == "__main__":
    unittest.main()
