import os
import time
import unittest

os.environ.setdefault("JWT_SECRET", "test-only-secret-for-local-auth-tests")

from app.core.auth import _encode, authenticate, decode_token, hash_password, issue_token, verify_password
from app.core.persistence import UserAccountRow, engine, initialize
from sqlalchemy.orm import Session


class JWTAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def test_valid_login_and_claims(self):
        user = authenticate("CITIZEN_001", "rahul@2026")
        self.assertEqual(user["role"], "CITIZEN")
        claims = decode_token(issue_token(user))
        self.assertEqual(claims["sub"], "CITIZEN_001")
        self.assertEqual(claims["role"], "CITIZEN")
        self.assertIn("iat", claims); self.assertIn("exp", claims); self.assertIn("jti", claims)

    def test_wrong_password_and_unknown_user(self):
        self.assertIsNone(authenticate("CITIZEN_001", "wrong-password"))
        self.assertIsNone(authenticate("UNKNOWN_USER", "wrong-password"))

    def test_tampered_and_expired_tokens_are_rejected(self):
        user = authenticate("CITIZEN_001", "rahul@2026")
        token = issue_token(user)
        with self.assertRaises(Exception): decode_token(token[:-1] + ("A" if token[-1] != "A" else "B"))
        expired = _encode({"sub": user["userId"], "role": user["role"], "iat": int(time.time()) - 20, "exp": int(time.time()) - 1, "jti": "expired-test"})
        with self.assertRaises(Exception): decode_token(expired)

    def test_password_is_hashed_not_plaintext(self):
        password = "test-password"
        hashed = hash_password(password)
        self.assertNotEqual(hashed, password)
        self.assertTrue(verify_password(password, hashed))
        with Session(engine) as session:
            account = session.get(UserAccountRow, "CITIZEN_001")
            self.assertNotEqual(account.password_hash, "rahul@2026")
            self.assertTrue(account.password_hash.startswith("scrypt$"))


if __name__ == "__main__":
    unittest.main()
