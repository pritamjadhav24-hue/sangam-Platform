from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.persistence import UserAccountRow, engine


def _load_local_env() -> None:
    if os.getenv("JWT_SECRET"):
        return
    for path in (Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[3] / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("JWT_SECRET="):
                    os.environ["JWT_SECRET"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return


_load_local_env()
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is required; set it in the environment or local .env file.")
JWT_EXPIRES_SECONDS = int(os.getenv("JWT_EXPIRES_SECONDS", "1800"))
_bearer = HTTPBearer(auto_error=False)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1${}${}".format(_b64(salt), _b64(digest))


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, digest_value = stored.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt_value), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, _unb64(digest_value))
    except (ValueError, TypeError):
        return False


def _encode(payload: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def decode_token(token: str) -> dict:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), encoded_signature) or not hmac.compare_digest(expected, _unb64(encoded_signature)):
            raise ValueError("invalid signature")
        header = json.loads(_unb64(encoded_header))
        payload = json.loads(_unb64(encoded_payload))
        if header.get("alg") != "HS256" or payload.get("exp", 0) <= int(time.time()):
            raise ValueError("expired token")
        if not payload.get("sub") or not payload.get("role") or not payload.get("iat") or not payload.get("jti"):
            raise ValueError("incomplete token")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")


def authenticate(user_id: str, password: str) -> Optional[dict]:
    with Session(engine) as session:
        account = session.get(UserAccountRow, user_id)
        if not account or not verify_password(password, account.password_hash):
            return None
        return dict(account.payload)


def issue_token(user: dict) -> str:
    now = int(time.time())
    return _encode({"sub": user["userId"], "role": user["role"], "iat": now, "exp": now + JWT_EXPIRES_SECONDS, "jti": secrets.token_urlsafe(16)})


def current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    claims = decode_token(credentials.credentials)
    with Session(engine) as session:
        account = session.get(UserAccountRow, claims["sub"])
        if not account or account.role != claims["role"]:
            raise HTTPException(status_code=401, detail="Account is no longer valid.")
        return dict(account.payload)


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail=f"Role {user.get('role')} is not allowed for this resource.")
        return user
    return dependency


def demo_citizen_switch_enabled() -> bool:
    """Gate for the demo citizen switcher (list + switch-to endpoints).

    Mirrors the existing SANGAM_ALLOW_DEMO_FALLBACK pattern used throughout
    the engine layer (app.engine.registry._demo_fallback_enabled,
    app.engine.adapters): off by default, and impossible to enable at all
    when SANGAM_ENV=production, regardless of the flag's value. This is a
    demo/QA convenience, never a real authentication path -- it never
    accepts a password and only ever issues a token for an account already
    explicitly marked isDemoCitizen (see persistence.ensure_demo_citizen_accounts).
    """
    mode = os.getenv("SANGAM_ENV", "development").strip().lower()
    return mode not in {"production", "prod"} and os.getenv("SANGAM_ALLOW_DEMO_CITIZEN_SWITCH", "false").lower() in {"1", "true", "yes"}


def public_demo_enabled() -> bool:
    """Explicit public-demonstration mode (SANGAM_PUBLIC_DEMO=true): the
    sign-in page offers the curated demo citizens (app.seeds.demo_citizens)
    and signs in as one of them without a password. Off by default. It only
    ever issues a token for an account marked isPublicDemo -- never for a
    real citizen, officer or administrator -- and does not change normal
    password authentication in any way."""
    return os.getenv("SANGAM_PUBLIC_DEMO", "false").strip().lower() in {"1", "true", "yes"}
