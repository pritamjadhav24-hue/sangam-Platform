from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

from app.mocks.identity_provider import user_for_token

_bearer = HTTPBearer(auto_error=False)


def current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = user_for_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return user


def require_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail=f"Role {user.get('role')} is not allowed for this resource.")
        return user
    return dependency
