from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.audit_bus import audit_bus
from app.core.auth import authenticate, demo_citizen_switch_enabled, issue_token
from app.core.persistence import UserAccountRow, engine
from app.core.rate_limit import enforce

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
class Login(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=1, max_length=256)
@router.post("/login")
def login(body: Login):
    enforce("login", body.citizenId, limit=10, window_seconds=60)
    user = authenticate(body.citizenId, body.password)
    audit_bus.append(body.citizenId, "IDENTITY", "Local JWT login", "GovOrchestrator", "VERIFY", payload={"success": bool(user), "role": user.get("role") if user else None})
    if not user: raise HTTPException(401, "Identity verification failed. Check credentials and retry.")
    return {"verified": True, "token": issue_token(user), "user": user, "citizen": user if user["role"] == "CITIZEN" else None}


class DemoLogin(BaseModel):
    citizenId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/demo-citizens")
def demo_citizens():
    """DEMO ONLY: list the synthetic citizens the demo switcher can log in
    as -- name/persona/district only, never a password or credential. This
    is a backend-driven list (queries the real seeded accounts), not a
    hardcoded frontend array, and only ever returns accounts explicitly
    marked isDemoCitizen by persistence.ensure_demo_citizen_accounts.
    """
    if not demo_citizen_switch_enabled():
        raise HTTPException(status_code=404, detail="Demo citizen switching is not enabled.")
    with Session(engine) as session:
        rows = session.query(UserAccountRow).filter(UserAccountRow.role == "CITIZEN").all()
    citizens = [
        {"citizenId": row.user_id, "name": row.payload.get("name"), "persona": row.payload.get("persona"), "district": row.payload.get("district")}
        for row in rows if row.payload.get("isDemoCitizen")
    ]
    citizens.sort(key=lambda item: item["citizenId"])
    return {"citizens": citizens}


@router.post("/demo-login")
def demo_login(body: DemoLogin):
    """DEMO ONLY: issue a real JWT for a demo-switchable citizen without a
    password. This genuinely switches the authenticated context (a real
    token for that citizen's real account), not client-side state -- every
    endpoint the citizen then calls sees them as that citizen. Restricted to
    accounts explicitly marked isDemoCitizen; cannot be used to authenticate
    as an arbitrary citizen, officer, or admin account.
    """
    if not demo_citizen_switch_enabled():
        raise HTTPException(status_code=404, detail="Demo citizen switching is not enabled.")
    enforce("demo_login", body.citizenId, limit=30, window_seconds=60)
    with Session(engine) as session:
        account = session.get(UserAccountRow, body.citizenId)
        user = dict(account.payload) if account and account.role == "CITIZEN" and account.payload.get("isDemoCitizen") else None
    audit_bus.append(body.citizenId, "IDENTITY", "Demo citizen switch", "GovOrchestrator", "DEMO_SWITCH", payload={"success": bool(user)})
    if not user:
        raise HTTPException(status_code=404, detail="This citizen is not available for demo switching.")
    return {"verified": True, "token": issue_token(user), "user": user, "citizen": user}
