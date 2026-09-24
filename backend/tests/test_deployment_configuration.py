import os
import unittest
from unittest.mock import patch

from app.core.persistence import validate_production_configuration


class DeploymentConfigurationTests(unittest.TestCase):
    def test_production_rejects_demo_seeding(self):
        with patch.dict(os.environ, {"SANGAM_ENV": "production", "SANGAM_SEED_CATALOG": "true"}):
            with self.assertRaisesRegex(RuntimeError, "Demo catalog/user seeding"):
                validate_production_configuration()

    def test_production_rejects_weak_or_placeholder_jwt_secret(self):
        base = {"SANGAM_ENV": "production", "SANGAM_SEED_CATALOG": "false", "SANGAM_SEED_DEMO_USERS": "false",
                "SANGAM_SEED_SYNTHETIC_DATA": "false", "SANGAM_SEED_DEPARTMENT_PROVIDERS": "false"}
        for secret in ("short", "replace-with-a-long-random-local-secret-value-here"):
            with patch.dict(os.environ, {**base, "JWT_SECRET": secret}):
                with self.assertRaisesRegex(RuntimeError, "JWT_SECRET"):
                    validate_production_configuration()

    def test_production_rejects_local_cors(self):
        with patch.dict(os.environ, {"SANGAM_ENV": "production", "SANGAM_SEED_CATALOG": "false", "SANGAM_SEED_DEMO_USERS": "false", "SANGAM_SEED_SYNTHETIC_DATA": "false", "SANGAM_SEED_DEPARTMENT_PROVIDERS": "false", "JWT_SECRET": "x" * 48, "CORS_ALLOWED_ORIGINS": "http://localhost:5173"}):
            with self.assertRaisesRegex(RuntimeError, "non-local CORS"):
                validate_production_configuration()


if __name__ == "__main__":
    unittest.main()
