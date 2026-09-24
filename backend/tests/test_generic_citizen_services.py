import unittest

from app.core.demo_state import reset_demo_state
from app.core.persistence import citizen_service_snapshot
from app.engine.requirement_analyzer import discover
from app.engine.rules_engine import evaluate
from app.engine.workflow_engine import create_application


class GenericCitizenServiceTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def _citizen(self):
        return {"citizenId": "CITIZEN_001", "name": "Asha Patil", "dob": "2004-02-12", "phone": "9000000001"}

    def test_catalog_exposes_two_services_with_distinct_db_requirements(self):
        services = citizen_service_snapshot()
        by_id = {item["serviceId"]: item for item in services}
        self.assertIn("SCH-MH-2026", by_id)
        self.assertIn("EDU-ACADEMIC-2026", by_id)
        self.assertNotEqual(
            {item["code"] for item in by_id["SCH-MH-2026"]["requirements"]},
            {item["code"] for item in by_id["EDU-ACADEMIC-2026"]["requirements"]},
        )
        self.assertNotIn("provider", by_id["EDU-ACADEMIC-2026"])

    def test_same_discovery_and_workflow_engine_creates_generic_application(self):
        discovery = discover(self._citizen(), service_id="EDU-ACADEMIC-2026")
        self.assertEqual(discovery["serviceId"], "EDU-ACADEMIC-2026")
        app = create_application("CITIZEN_001", discovery, evaluate(discovery["requirements"]), "EDU-ACADEMIC-2026")
        self.assertTrue(app["appId"].startswith("APP-EDU-ACADEMIC-2026-"))
        self.assertEqual(app["serviceId"], "EDU-ACADEMIC-2026")
        self.assertEqual([item["stage"] for item in app["timeline"]], ["Submitted", "Requirements", "Verification", "Officer Review", "Completed"])


# Remove every runtime row (applications, consents, documents, notifications,
# provider jobs/incidents) this module leaves in the shared database.
from tests.catalog_fixture import guard_module_runtime_state  # noqa: E402
guard_module_runtime_state(globals())


if __name__ == "__main__":
    unittest.main()
