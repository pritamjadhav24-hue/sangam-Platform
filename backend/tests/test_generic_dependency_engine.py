import unittest

from app.core.demo_state import reset_demo_state
from app.engine.adapters import integration_health, set_integration_availability
from app.engine.dependency_orchestrator import ensure_dependency, initiate_dependency
from app.engine.registry import select_dependency_provider


class GenericDependencyEngineTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()
        set_integration_availability("Revenue Department", True)
        set_integration_availability("Education Department", True)

    def _app(self, app_id, requirement_code):
        return {
            "appId": app_id,
            "citizenId": "CITIZEN_001",
            "status": "WAITING_FOR_DEPENDENCY",
            "dependencyIds": [],
            "dependencies": [],
            "requirements": [{"code": requirement_code, "status": "MISSING"}],
            "entityReviews": [],
            "conflictReviews": [],
            "statusHistory": [{"status": "WAITING_FOR_DEPENDENCY", "at": "2026-01-01T00:00:00+00:00"}],
        }

    def test_two_configured_capabilities_use_same_engine(self):
        health = integration_health()
        domicile_provider = select_dependency_provider("DOMICILE_PROOF", health)
        academic_provider = select_dependency_provider("ACADEMIC_RECORD", health)
        self.assertEqual(domicile_provider["serviceId"], "REV-MAHA-101")
        self.assertEqual(academic_provider["serviceId"], "EDU-ACA-201")

        domicile_app = self._app("GENERIC-DOMICILE", "DOMICILE_PROOF")
        academic_app = self._app("GENERIC-ACADEMIC", "ACADEMIC_RECORD")
        self.assertEqual(ensure_dependency(domicile_app, "DOMICILE_PROOF")["providerService"], "REV-MAHA-101")
        self.assertEqual(ensure_dependency(academic_app, "ACADEMIC_RECORD")["providerService"], "EDU-ACA-201")
        self.assertTrue(initiate_dependency("CITIZEN_001", academic_app, "ACADEMIC_RECORD")["success"])


if __name__ == "__main__":
    unittest.main()
