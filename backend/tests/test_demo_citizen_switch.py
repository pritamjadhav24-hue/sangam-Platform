"""Phase 6F1: demo citizen switching.

Verifies the switcher is backend-driven (never a hardcoded frontend list),
genuinely switches the authenticated identity (a real JWT for a real
UserAccountRow, not client-side state), is environment-gated, and can never
be used to authenticate as a non-demo citizen or as an officer/admin.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.auth_routes import DemoLogin, demo_citizens, demo_login
from app.core.persistence import (
    CitizenRow, UserAccountRow, engine, ensure_demo_citizen_accounts,
    select_demo_switchable_citizen_ids, seed_platform_citizens,
)


def setUpModule():
    with patch.dict("os.environ", {"SANGAM_SEED_SYNTHETIC_DATA": "true"}):
        seed_platform_citizens()
    with patch.dict("os.environ", {"SANGAM_SEED_DEMO_USERS": "true", "SANGAM_DEMO_CITIZEN_PASSWORD": "test-demo-password-not-real"}):
        ensure_demo_citizen_accounts()


def tearDownModule():
    citizen_ids = select_demo_switchable_citizen_ids()
    with Session(engine) as session:
        session.query(UserAccountRow).filter(UserAccountRow.user_id.in_(citizen_ids)).delete(synchronize_session=False)
        session.commit()


class DemoCitizenSelectionTests(unittest.TestCase):
    def test_selection_is_deterministic_and_persona_diverse(self):
        first = select_demo_switchable_citizen_ids()
        second = select_demo_switchable_citizen_ids()
        self.assertEqual(first, second, "selection must be deterministic across calls")
        with Session(engine) as session:
            rows = session.query(CitizenRow).filter(CitizenRow.citizen_id.in_(first)).all()
        personas = {row.persona for row in rows}
        self.assertGreater(len(personas), 1, "the selection must span more than one persona")

    def test_demo_accounts_carry_real_citizen_row_data_not_a_hardcoded_profile(self):
        citizen_ids = select_demo_switchable_citizen_ids()
        with Session(engine) as session:
            citizen_rows = {row.citizen_id: row for row in session.query(CitizenRow).filter(CitizenRow.citizen_id.in_(citizen_ids)).all()}
            account_rows = {row.user_id: row for row in session.query(UserAccountRow).filter(UserAccountRow.user_id.in_(citizen_ids)).all()}
        for citizen_id in citizen_ids:
            citizen = citizen_rows[citizen_id]
            account = account_rows[citizen_id]
            self.assertEqual(account.payload["name"], citizen.full_name)
            self.assertEqual(account.payload["dob"], citizen.date_of_birth)
            self.assertEqual(account.payload["district"], citizen.district)
            self.assertEqual(account.payload["persona"], citizen.persona)
            self.assertTrue(account.payload["isDemoCitizen"])


class DemoCitizenSwitchEndpointTests(unittest.TestCase):
    def test_listing_and_login_are_disabled_by_default(self):
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "false"}):
            with self.assertRaises(HTTPException) as ctx:
                demo_citizens()
            self.assertEqual(ctx.exception.status_code, 404)
            with self.assertRaises(HTTPException) as ctx:
                demo_login(DemoLogin(citizenId=select_demo_switchable_citizen_ids()[0]))
            self.assertEqual(ctx.exception.status_code, 404)

    def test_listing_never_includes_a_password_or_credential(self):
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "development"}):
            result = demo_citizens()
        self.assertGreater(len(result["citizens"]), 0)
        for citizen in result["citizens"]:
            self.assertEqual(set(citizen), {"citizenId", "name", "persona", "district"})

    def test_login_issues_a_real_token_for_the_target_demo_citizen(self):
        citizen_id = select_demo_switchable_citizen_ids()[0]
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "development"}):
            result = demo_login(DemoLogin(citizenId=citizen_id))
        self.assertTrue(result["verified"])
        self.assertEqual(result["user"]["citizenId"], citizen_id)
        self.assertEqual(result["user"]["role"], "CITIZEN")
        # The token is real and usable: decoding it identifies this exact citizen.
        from app.core.auth import decode_token
        claims = decode_token(result["token"])
        self.assertEqual(claims["sub"], citizen_id)
        self.assertEqual(claims["role"], "CITIZEN")

    def test_login_rejects_a_citizen_not_in_the_demo_set(self):
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "development"}):
            with self.assertRaises(HTTPException) as ctx:
                demo_login(DemoLogin(citizenId="SYN-CIT-00059"))  # real citizen, never seeded as demo-loginable
        self.assertEqual(ctx.exception.status_code, 404)

    def test_login_cannot_be_used_to_authenticate_as_an_officer_or_admin(self):
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "development"}):
            with self.assertRaises(HTTPException) as ctx:
                demo_login(DemoLogin(citizenId="OFFICER_MH_01"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_switch_disabled_in_production_regardless_of_flag(self):
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "production"}):
            with self.assertRaises(HTTPException) as ctx:
                demo_citizens()
        self.assertEqual(ctx.exception.status_code, 404)

    def test_three_different_demo_citizens_have_distinct_profiles(self):
        citizen_ids = select_demo_switchable_citizen_ids()[:3]
        self.assertEqual(len(citizen_ids), 3)
        with patch.dict("os.environ", {"SANGAM_ALLOW_DEMO_CITIZEN_SWITCH": "true", "SANGAM_ENV": "development"}):
            profiles = [demo_login(DemoLogin(citizenId=cid))["user"] for cid in citizen_ids]
        names = {profile["name"] for profile in profiles}
        personas = {profile["persona"] for profile in profiles}
        self.assertEqual(len(names), 3, "three different demo citizens must have three different names")
        self.assertEqual(len(personas), 3, "the selected demo citizens must have distinct personas")


if __name__ == "__main__":
    unittest.main()
