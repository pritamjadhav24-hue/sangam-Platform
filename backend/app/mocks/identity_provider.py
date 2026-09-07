import secrets

CITIZENS = {
    "CITIZEN_001": {"citizenId": "CITIZEN_001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "password": "rahul@2026"}
}


def verify_sso(citizen_id: str, password: str) -> dict:
    citizen = CITIZENS.get(citizen_id)
    if not citizen or citizen["password"] != password:
        return {"verified": False, "message": "Identity verification failed. Check credentials and retry."}
    return {"verified": True, "token": f"gov_{secrets.token_urlsafe(24)}", "citizen": {k: v for k, v in citizen.items() if k != "password"}}
