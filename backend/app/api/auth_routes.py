from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.audit_bus import audit_bus
from app.core.auth import authenticate, issue_token

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
class Login(BaseModel): citizenId: str; password: str
@router.post("/login")
def login(body: Login):
    user = authenticate(body.citizenId, body.password)
    audit_bus.append(body.citizenId, "IDENTITY", "Local JWT login", "GovOrchestrator", "VERIFY", payload={"success": bool(user), "role": user.get("role") if user else None})
    if not user: raise HTTPException(401, "Identity verification failed. Check credentials and retry.")
    return {"verified": True, "token": issue_token(user), "user": user, "citizen": user if user["role"] == "CITIZEN" else None}
