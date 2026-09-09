from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.audit_bus import audit_bus
from app.mocks.identity_provider import verify_sso

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
class Login(BaseModel): citizenId: str; password: str
@router.post("/login")
def login(body: Login):
    result = verify_sso(body.citizenId, body.password)
    audit_bus.append(body.citizenId, "IDENTITY", "Federated SSO login", "Civil Registry", "VERIFY", payload={"success": result["verified"], "role": result.get("user", {}).get("role")})
    if not result["verified"]: raise HTTPException(401, result["message"])
    return result
