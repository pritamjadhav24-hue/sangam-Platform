USERS = {
    "CITIZEN_001": {"userId": "CITIZEN_001", "citizenId": "CITIZEN_001", "name": "Rahul Kumar", "dob": "2005-06-15", "phone": "+91-9876543210", "role": "CITIZEN"},
    "CITIZEN_002": {"userId": "CITIZEN_002", "citizenId": "CITIZEN_002", "name": "Asha Patil", "dob": "2004-02-11", "phone": "+91-9000000002", "role": "CITIZEN"},
    "OFFICER_MH_01": {"userId": "OFFICER_MH_01", "name": "Maharashtra Officer", "role": "OFFICER"},
    "ADMIN_MH_01": {"userId": "ADMIN_MH_01", "name": "Platform Administrator", "role": "ADMIN"},
}
CITIZENS = {key: value for key, value in USERS.items() if value["role"] == "CITIZEN"}
SESSIONS = {}
