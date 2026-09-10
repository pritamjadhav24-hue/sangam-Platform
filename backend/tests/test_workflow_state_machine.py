import unittest

from app.core.demo_state import reset_demo_state
from app.core.persistence import persist_state
from app.engine.workflow_engine import VALID_TRANSITIONS, transition_application


def make_app(status: str, suffix: str) -> dict:
    return {"appId": f"STATE-{suffix}-{status}", "citizenId": "CITIZEN_001", "status": status, "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-01-01T00:00:00+00:00", "statusHistory": [{"status": status, "at": "2026-01-01T00:00:00+00:00"}], "requirements": [], "eligibility": {}}


class WorkflowStateMachineTests(unittest.TestCase):
    def setUp(self):
        reset_demo_state()

    def tearDown(self):
        reset_demo_state()
        persist_state()

    def test_every_declared_valid_transition_is_accepted(self):
        count = 0
        for current, targets in VALID_TRANSITIONS.items():
            for target in targets:
                app = make_app(current, f"{count:03d}")
                transition_application(app, target, actor="TEST", source="workflow_test")
                self.assertEqual(app["status"], target)
                self.assertEqual(app["statusHistory"][-1]["status"], target)
                self.assertEqual(app["statusHistory"][-1]["actor"], "TEST")
                count += 1
        self.assertGreater(count, 20)

    def test_every_undeclared_transition_is_rejected_without_mutation(self):
        count = 0
        for current in VALID_TRANSITIONS:
            for target in VALID_TRANSITIONS:
                if target in VALID_TRANSITIONS[current] or target == current:
                    continue
                app = make_app(current, f"INVALID-{count:03d}")
                before_history = list(app["statusHistory"])
                with self.assertRaises(ValueError):
                    transition_application(app, target)
                self.assertEqual(app["status"], current)
                self.assertEqual(app["statusHistory"], before_history)
                count += 1
        self.assertGreater(count, 50)

    def test_all_terminal_states_have_no_outgoing_transitions(self):
        for terminal in ("REJECTED", "COMPLETED", "CANCELLED"):
            self.assertEqual(VALID_TRANSITIONS[terminal], set())
            for target in VALID_TRANSITIONS:
                if target == terminal:
                    continue
                with self.assertRaises(ValueError):
                    transition_application(make_app(terminal, target), target)

    def test_history_is_consistent_across_a_valid_journey(self):
        app = make_app("DRAFT", "JOURNEY")
        for target in ("IN_PROGRESS", "WAITING_FOR_DEPENDENCY", "IN_PROGRESS", "SUBMITTED", "WAITING_FOR_OFFICER", "APPROVED", "COMPLETED"):
            transition_application(app, target)
        self.assertEqual([entry["status"] for entry in app["statusHistory"]], ["DRAFT", "IN_PROGRESS", "WAITING_FOR_DEPENDENCY", "IN_PROGRESS", "SUBMITTED", "WAITING_FOR_OFFICER", "APPROVED", "COMPLETED"])


if __name__ == "__main__":
    unittest.main()
