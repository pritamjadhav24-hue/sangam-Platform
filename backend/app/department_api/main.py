"""Entry point for the simulated department sandbox API service.

Run locally with:  python -m uvicorn app.department_api.main:app --port 9101
This is a separate process/service from SANGAM's own backend (``main.py``) --
it is the only process that touches ``app.sandbox`` databases, and SANGAM
reaches it exclusively over HTTP via the provider/adapter layer.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from app.department_api.common import SYNTHETIC_DISCLAIMER
from app.department_api.routers import (
    agriculture, education, food_civil_supplies, housing, labour,
    municipal_health, revenue, skill_employment, social_welfare, transport,
)

app = FastAPI(
    title="SANGAM Department Sandbox APIs",
    description=SYNTHETIC_DISCLAIMER,
    version="1.0.0",
)

@app.on_event("startup")
def prepare_sandbox_databases():
    """Make a fresh deployment (e.g. an empty Compose volume) serve data
    without a manual step: create each department's tables and load its
    deterministic synthetic seed. Idempotent -- every department seed skips
    itself when already populated, so restarts never duplicate or reset data.
    Set DEPARTMENT_SANDBOX_AUTO_SEED=false to manage sandboxes by hand
    (python -m app.sandbox.manage ...)."""
    if os.getenv("DEPARTMENT_SANDBOX_AUTO_SEED", "true").lower() not in {"1", "true", "yes"}:
        return
    from app.sandbox.manage import seed_all
    seed_all()


for router in (
    revenue.router, education.router, social_welfare.router, agriculture.router,
    transport.router, labour.router, food_civil_supplies.router, housing.router,
    skill_employment.router, municipal_health.router,
):
    app.include_router(router)


@app.get("/")
def root():
    return {"service": "SANGAM Department Sandbox APIs", "synthetic": True, "disclaimer": SYNTHETIC_DISCLAIMER}


@app.get("/health")
def health():
    return {"status": "AVAILABLE", "synthetic": True}
