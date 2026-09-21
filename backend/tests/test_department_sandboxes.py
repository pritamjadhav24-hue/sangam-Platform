"""Tests for the independent, simulated department sandbox architecture.

These sandboxes are deliberately separate databases from SANGAM's own
PostgreSQL database. These tests check: (1) every registered department
sandbox has a working, isolated schema and idempotent seed function, (2) the
same synthetic citizen appears -- with department-appropriate field
differences -- across multiple independent sandboxes, (3) seeded data
includes positive/pending/failure (and missing-by-absence) cases, and (4)
SANGAM's request-handling code never imports the sandbox package, preserving
the "SANGAM never directly accesses department databases" boundary.
"""
import ast
import importlib
import unittest
from pathlib import Path

from app.sandbox.common import session_scope
from app.sandbox.registry import SANDBOXES
from app.seeds.synthetic_identity_pool import citizens_with_persona, generate_citizen_pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CITIZENS = generate_citizen_pool(60)


def _load(spec):
    return importlib.import_module(spec.models_module), importlib.import_module(spec.seed_module)


def _reset(models):
    models.Base.metadata.drop_all(models.ENGINE)
    models.Base.metadata.create_all(models.ENGINE)


class DepartmentSandboxSchemaTests(unittest.TestCase):
    def test_registry_covers_a_broad_department_set(self):
        self.assertGreaterEqual(len(SANDBOXES), 10)
        self.assertEqual(len({spec.key for spec in SANDBOXES}), len(SANDBOXES))

    def test_every_sandbox_has_isolated_engine_and_creates_cleanly(self):
        for spec in SANDBOXES:
            with self.subTest(department=spec.key):
                models, _ = _load(spec)
                _reset(models)
                self.assertGreater(len(models.Base.metadata.tables), 0)
                from app.core.persistence import DATABASE_URL
                self.assertNotEqual(str(models.ENGINE.url), DATABASE_URL)

    def test_every_sandbox_seed_is_deterministic_and_idempotent(self):
        for spec in SANDBOXES:
            with self.subTest(department=spec.key):
                models, seed = _load(spec)
                _reset(models)
                with session_scope(models.ENGINE) as session:
                    first = seed.seed(session, CITIZENS)
                with session_scope(models.ENGINE) as session:
                    second = seed.seed(session, CITIZENS)  # already seeded -> no-op
                self.assertNotEqual(first, {"skipped": True})
                self.assertEqual(second, {"skipped": True})

    def test_seeded_departments_contain_multiple_case_outcomes(self):
        """Every department with status-bearing rows should show more than one
        outcome (not just POSITIVE), demonstrating pending/failure coverage."""
        for spec in SANDBOXES:
            with self.subTest(department=spec.key):
                models, seed = _load(spec)
                _reset(models)
                with session_scope(models.ENGINE) as session:
                    seed.seed(session, CITIZENS)
                with session_scope(models.ENGINE) as session:
                    statuses = set()
                    for table in models.Base.metadata.tables.values():
                        if "status" not in table.c:
                            continue
                        rows = session.execute(table.select().with_only_columns(table.c.status)).scalars().all()
                        statuses.update(rows)
                if statuses:
                    self.assertGreater(len(statuses), 1, f"{spec.key} only produced status values {statuses}")


class CrossDepartmentIdentityTests(unittest.TestCase):
    def test_same_citizen_id_appears_across_multiple_department_sandboxes(self):
        student = citizens_with_persona(CITIZENS, "STUDENT")[0]
        farmer_candidates = citizens_with_persona(CITIZENS, "FARMER")

        from app.sandbox.education import models as education_models
        from app.sandbox.revenue import models as revenue_models
        _reset(revenue_models)
        _reset(education_models)
        from app.sandbox.revenue import seed as revenue_seed
        from app.sandbox.education import seed as education_seed
        with session_scope(revenue_models.ENGINE) as session:
            revenue_seed.seed(session, CITIZENS)
        with session_scope(education_models.ENGINE) as session:
            education_seed.seed(session, CITIZENS)

        with session_scope(revenue_models.ENGINE) as session:
            revenue_refs = {row.citizen_ref for row in session.query(revenue_models.ResidentIndex).all()}
        with session_scope(education_models.ENGINE) as session:
            education_refs = {row.citizen_ref for row in session.query(education_models.Student).all()}

        # Every citizen has a Revenue resident_index row; students additionally
        # appear in Education. The same citizen_id must resolve in both.
        self.assertIn(student["citizenId"], revenue_refs)
        self.assertIn(student["citizenId"], education_refs)
        self.assertTrue(farmer_candidates, "expected at least one FARMER persona in the synthetic pool")

    def test_department_representations_of_the_same_citizen_differ_in_shape(self):
        from app.sandbox.revenue import models as revenue_models
        from app.sandbox.social_welfare import models as social_welfare_models
        _reset(revenue_models)
        _reset(social_welfare_models)
        from app.sandbox.revenue import seed as revenue_seed
        from app.sandbox.social_welfare import seed as social_welfare_seed
        with session_scope(revenue_models.ENGINE) as session:
            revenue_seed.seed(session, CITIZENS)
        with session_scope(social_welfare_models.ENGINE) as session:
            social_welfare_seed.seed(session, CITIZENS)

        revenue_columns = {column.name for column in revenue_models.ResidentIndex.__table__.columns}
        social_welfare_columns = {column.name for column in social_welfare_models.Beneficiary.__table__.columns}
        # Different departments name the same concept differently (mobile vs
        # phone) and use different primary-key/table shapes entirely.
        self.assertIn("mobile", social_welfare_columns)
        self.assertIn("full_name", revenue_columns)
        self.assertNotEqual(revenue_models.ResidentIndex.__tablename__, social_welfare_models.Beneficiary.__tablename__)


class SandboxIsolationTests(unittest.TestCase):
    def test_core_engine_and_api_modules_never_import_the_sandbox_package(self):
        offenders = []
        for directory in ("app/core", "app/engine", "app/api"):
            for path in (BACKEND_ROOT / directory).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    else:
                        continue
                    if any(name == "app.sandbox" or name.startswith("app.sandbox.") for name in names):
                        offenders.append(str(path.relative_to(BACKEND_ROOT)))
        self.assertEqual(offenders, [], f"SANGAM request-handling code must not import department sandboxes: {offenders}")


if __name__ == "__main__":
    unittest.main()
