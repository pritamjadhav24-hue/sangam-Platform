"""health API service (see app.department_api.service)."""
from app.department_api.service import create_app

app = create_app("health")
