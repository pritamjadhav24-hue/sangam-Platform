import secrets

USERS = {
    "CITIZEN_001": {"userId": "CITIZEN_001", "citizenId": "CITIZEN_001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "password": "rahul@2026", "role": "CITIZEN"},
    "CITIZEN_002": {"userId": "CITIZEN_002", "citizenId": "CITIZEN_002", "name": "Asha Patil", "dob": "2004-02-11", "phone": "+91-9000000002", "password": "asha@2026", "role": "CITIZEN"},
    "OFFICER_MH_01": {"userId": "OFFICER_MH_01", "name": "Maharashtra Officer", "password": "officer@2026", "role": "OFFICER"},
    "ADMIN_MH_01": {"userId": "ADMIN_MH_01", "name": "Platform Administrator", "password": "admin@2026", "role": "ADMIN"},
}
CITIZENS = {key: value for key, value in USERS.items() if value["role"] == "CITIZEN"}
SESSIONS = {}


def verify_sso(citizen_id: str, password: str) -> dict:
    user = USERS.get(citizen_id)
    if not user or user["password"] != password:
        return {"verified": False, "message": "Identity verification failed. Check credentials and retry."}
    token = f"gov_{secrets.token_urlsafe(24)}"
    public_user = {k: v for k, v in user.items() if k != "password"}
    SESSIONS[token] = public_user
    return {"verified": True, "token": token, "user": public_user, "citizen": public_user if user["role"] == "CITIZEN" else None}


def user_for_token(token: str):
    return SESSIONS.get(token)
