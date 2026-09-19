from app.seeds.demo import USERS
CITIZENS = {key: value for key, value in USERS.items() if value["role"] == "CITIZEN"}
SESSIONS = {}
