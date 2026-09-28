from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os

from fastapi.middleware.cors import CORSMiddleware
from app.api import admin_routes, auth_routes, citizen_routes, officer_routes, catalog_routes
from app.api import notification_routes
import app.core.notification_manager
from app.core.persistence import ensure_demo_citizen_accounts, ensure_public_demo_accounts, ensure_user_accounts, federate_department_providers, initialize, hydrate_state, persist_state, seed_catalog, seed_department_sandbox_providers, seed_department_sandbox_schema_mappings, seed_platform_citizens, seed_requirement_catalog, seed_schema_mappings, validate_production_configuration, worker_operational_status
from app.core.redis_service import RedisService

_production = os.getenv("SANGAM_ENV", "development").strip().lower() in {"production", "prod"}
# Interactive API docs are a development aid; production does not publish them.
app = FastAPI(title="GovOrchestrator", version="1.0.0", description="Purpose-bound federated government service orchestration",
              docs_url=None if _production else "/docs", redoc_url=None if _production else "/redoc",
              openapi_url=None if _production else "/openapi.json")
_cors_origins = [origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
if "*" in _cors_origins and os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {"1", "true", "yes"}:
    raise RuntimeError("CORS wildcard origins cannot be used with credentials.")
_cors_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {"1", "true", "yes"}
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_credentials=_cors_credentials, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Accept", "X-Correlation-ID"])
app.include_router(auth_routes.router); app.include_router(citizen_routes.router); app.include_router(officer_routes.router); app.include_router(admin_routes.router); app.include_router(notification_routes.router); app.include_router(catalog_routes.router)

def load_integration_env() -> None:
    """SANGAM's own endpoints for the department APIs (DEPARTMENT_API_URL_<DEPT>),
    from backend/.env.integrations when present. Loaded at startup only, so
    importing this module (e.g. in tests) never points code at live services."""
    from pathlib import Path
    path = Path(__file__).resolve().parent / ".env.integrations"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@app.on_event("startup")
def startup_persistence():
    load_integration_env()
    initialize()
    validate_production_configuration()
    RedisService().health_check()
    ensure_user_accounts()
    seed_catalog()
    seed_requirement_catalog()
    seed_schema_mappings()
    seed_platform_citizens()
    ensure_demo_citizen_accounts()
    ensure_public_demo_accounts()
    seed_department_sandbox_providers()
    seed_department_sandbox_schema_mappings()
    federate_department_providers()
    hydrate_state()

@app.middleware("http")
async def persist_after_request(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if not request.url.path.startswith("/health/") and response.status_code < 500 and not getattr(request.state, "application_write_authoritative", False):
        persist_state()
    return response


@app.exception_handler(Exception)
async def safe_unhandled_error(request: Request, error: Exception):
    return JSONResponse(status_code=500, content={"detail": "The service could not complete this request."})

@app.get("/")
def health(): return {"service": "GovOrchestrator", "status": "running", "centralDocumentStore": False}


@app.get("/health/live")
def liveness(): return {"status": "alive"}


@app.get("/health/ready")
def readiness():
    from fastapi import HTTPException
    try:
        initialize()
    except Exception as error:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "postgres": "UNAVAILABLE"}) from error
    redis_service = RedisService()
    try:
        redis = redis_service.health_check()
        workers = worker_operational_status() if redis_service.enabled else []
        worker = {"status": "DISABLED" if not redis_service.enabled else ("AVAILABLE" if redis_service.get("sangam:worker:heartbeat") and any(item["status"] == "AVAILABLE" for item in workers) else "UNAVAILABLE"), "workers": workers}
    except Exception as error:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "postgres": "AVAILABLE", "redis": "UNAVAILABLE"}) from error
    if redis_service.enabled and worker["status"] != "AVAILABLE":
        raise HTTPException(status_code=503, detail={"status": "not_ready", "postgres": "AVAILABLE", "redis": redis, "worker": worker})
    return {"status": "ready", "postgres": "AVAILABLE", "redis": redis, "worker": worker}
