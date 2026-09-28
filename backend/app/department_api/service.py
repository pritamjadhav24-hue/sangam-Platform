"""One independent API service per government department.

Each service is its own process (own port), mounts only its own
department's routes, and connects only to its own department database
(``SANDBOX_DB_URL_<DEPARTMENT>``). Departments never call each other or
SANGAM; SANGAM calls each of them through its provider registry.

Run a department (from the repository root):

    python -m uvicorn app.department_api.services.revenue:app --app-dir backend --port 9101

Database URLs come from the process environment or from
``backend/.env.departments`` -- a file only the department services read, so
SANGAM's own processes (and the test suite) never hold department database
credentials. ``app.department_api.main`` still mounts every department in
one process for tests and simple local runs.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

DEPARTMENT_SERVICES: dict[str, dict] = {
    "revenue": {"label": "Revenue Department", "keys": ["revenue"], "port": 9101},
    "education": {"label": "Education Department", "keys": ["education"], "port": 9102},
    "social_welfare": {"label": "Social Welfare Department", "keys": ["social_welfare"], "port": 9103},
    "health": {"label": "Health Department", "keys": ["municipal_health"], "port": 9104},
    "transport": {"label": "Transport Department", "keys": ["transport"], "port": 9105},
    "other": {"label": "Other Departments", "port": 9106,
              "keys": ["agriculture", "labour", "food_civil_supplies", "housing", "skill_employment"]},
}

# Each department's own PostgreSQL database (one per sandbox key).
DEPARTMENT_DATABASES = {
    "revenue": "revenue_db", "education": "education_db", "social_welfare": "welfare_db",
    "municipal_health": "health_db", "transport": "transport_db", "agriculture": "agriculture_db",
    "labour": "labour_db", "food_civil_supplies": "civil_supplies_db", "housing": "housing_db",
    "skill_employment": "skills_db",
}

DEPARTMENT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.departments"


def load_department_env(path: Path = DEPARTMENT_ENV_FILE) -> None:
    """Load KEY=VALUE lines into the environment for keys not already set.
    Must run before any ``app.sandbox.<dept>.models`` import (their engines
    are created at import time)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def create_app(service_key: str):
    load_department_env()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.department_api.common import SYNTHETIC_DISCLAIMER

    spec = DEPARTMENT_SERVICES[service_key]
    routers = {key: importlib.import_module(f"app.department_api.routers.{key}") for key in spec["keys"]}
    models = {key: importlib.import_module(f"app.sandbox.{key}.models") for key in spec["keys"]}

    app = FastAPI(title=f"{spec['label']} API", description=SYNTHETIC_DISCLAIMER, version="1.0.0")

    @app.on_event("startup")
    def prepare_department_database():
        # Idempotent: creates this department's tables and seeds synthetic
        # data only when empty (DEPARTMENT_SANDBOX_AUTO_SEED=false to skip).
        if os.getenv("DEPARTMENT_SANDBOX_AUTO_SEED", "true").lower() not in {"1", "true", "yes"}:
            return
        from app.sandbox.manage import seed_all
        seed_all(spec["keys"])

    for router_module in routers.values():
        app.include_router(router_module.router)

    @app.get("/")
    def root():
        return {"service": f"{spec['label']} API", "departments": spec["keys"], "synthetic": True, "disclaimer": SYNTHETIC_DISCLAIMER}

    @app.get("/health")
    def health():
        databases = {}
        for key, module in models.items():
            try:
                with module.ENGINE.connect() as connection:
                    connection.execute(text("SELECT 1"))
                databases[key] = "CONNECTED"
            except Exception:
                databases[key] = "UNAVAILABLE"
        ok = all(state == "CONNECTED" for state in databases.values())
        body = {"status": "AVAILABLE" if ok else "UNAVAILABLE", "department": spec["label"], "databases": databases, "synthetic": True}
        return body if ok else JSONResponse(status_code=503, content=body)

    return app
