from fastapi import FastAPI
import os

from fastapi.middleware.cors import CORSMiddleware
from app.api import admin_routes, auth_routes, citizen_routes, officer_routes, catalog_routes
from app.api import notification_routes
import app.core.notification_manager
from app.core.persistence import ensure_user_accounts, initialize, hydrate_state, persist_state, seed_catalog

app = FastAPI(title="GovOrchestrator", version="1.0.0", description="Purpose-bound federated government service orchestration")
_cors_origins = [origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_routes.router); app.include_router(citizen_routes.router); app.include_router(officer_routes.router); app.include_router(admin_routes.router); app.include_router(notification_routes.router); app.include_router(catalog_routes.router)

@app.on_event("startup")
def startup_persistence():
    initialize()
    ensure_user_accounts()
    seed_catalog()
    hydrate_state()

@app.middleware("http")
async def persist_after_request(request, call_next):
    response = await call_next(request)
    persist_state()
    return response

@app.get("/")
def health(): return {"service": "GovOrchestrator", "status": "running", "centralDocumentStore": False}
