from __future__ import annotations

import base64
import csv
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus
from app.core.provider_config import auth_references, validate_endpoint

ERROR_CATEGORIES = {"VALIDATION_ERROR", "AUTHENTICATION_ERROR", "AUTHORIZATION_ERROR", "CONFIGURATION_ERROR", "TIMEOUT", "NETWORK_ERROR", "UPSTREAM_UNAVAILABLE", "UPSTREAM_ERROR", "RATE_LIMITED", "MALFORMED_RESPONSE", "SCHEMA_MISMATCH", "UNSUPPORTED_OPERATION", "INTERNAL_ERROR"}
RETRYABLE_CATEGORIES = {"TIMEOUT", "NETWORK_ERROR", "UPSTREAM_UNAVAILABLE", "UPSTREAM_ERROR", "RATE_LIMITED"}
_availability, _last_health, _runtime_health = {}, {}, {}
_integrations = {"Civil Registry": {"adapterType": "Federated SSO", "service": "Identity verification"}, "Revenue Department": {"adapterType": "REST API", "service": "Income and domicile services"}, "Social Welfare Department": {"adapterType": "Legacy SOAP Wrapper", "service": "Caste verification"}, "Education Department": {"adapterType": "CSV/File Adapter", "service": "Academic records"}, "Authorized DBT": {"adapterType": "REST API", "service": "Bank account verification"}}


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _configured_integrations() -> dict:
    configured = {}
    try:
        from sqlalchemy.orm import Session
        from app.core.persistence import ProviderRow, ServiceCatalogRow, engine
        with Session(engine) as session:
            for provider in session.query(ProviderRow).filter_by(active=True).all():
                service = session.query(ServiceCatalogRow).filter_by(provider_id=provider.provider_id, active=True).first()
                service_payload = service.payload if service else {}
                configured[provider.name] = {"adapterType": provider.adapter_type, "service": service.name if service else "Configured provider service", "providerId": provider.provider_id, "contractVersion": provider.contract_version, "environment": provider.environment, "authType": provider.auth_type, "endpointRef": provider.endpoint_ref, "timeoutSeconds": provider.timeout_seconds, "maxAttempts": provider.max_attempts, "payload": {**service_payload, **(provider.payload or {})}}
    except Exception as error:
        mode = os.getenv("SANGAM_ENV", "development").strip().lower()
        allow_demo = mode not in {"production", "prod"} and os.getenv("SANGAM_ALLOW_DEMO_FALLBACK", "false").lower() in {"1", "true", "yes"}
        if not allow_demo:
            raise RuntimeError("Configured provider catalog is unavailable") from error
        configured = {}
    if configured:
        return configured
    mode = os.getenv("SANGAM_ENV", "development").strip().lower()
    if mode not in {"production", "prod"} and os.getenv("SANGAM_ALLOW_DEMO_FALLBACK", "false").lower() in {"1", "true", "yes"}:
        return _integrations
    return {}


@dataclass
class ProviderRequest:
    provider_id: str
    operation: str
    correlation_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    record: dict | None
    attempts: int = 1
    delayed: bool = False
    queued: bool = False
    provider: str | None = None
    operation: str = "retrieve"
    correlation_id: str | None = None
    idempotency_key: str | None = None
    response_ms: float | None = None
    error_category: str | None = None
    success: bool | None = None
    retryable: bool = False
    status_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def provider_id(self): return self.metadata.get("providerId") or self.provider
    @property
    def normalized_data(self): return self.record
    @property
    def duration_ms(self): return self.response_ms


ProviderResult = AdapterResult


class AdapterError(Exception):
    def __init__(self, message: str, category: str = "INTERNAL_ERROR", transient: bool | None = None, status_code: int | None = None):
        self.category = category if category in ERROR_CATEGORIES else "INTERNAL_ERROR"
        self.retryable = category in RETRYABLE_CATEGORIES if transient is None else transient
        self.status_code = status_code
        super().__init__(message)


class ProviderAdapter:
    kind = "GENERIC"
    requires_endpoint = True

    def __init__(self, source: str, fetcher: Callable | None = None, provider_id: str | None = None, config: dict | None = None):
        self.source, self.fetcher, self.provider_id = source, fetcher, provider_id or source
        self.config = {"environment": "SANDBOX", "authType": "NONE", "timeoutSeconds": 5, "maxAttempts": 3, **(config or {})}

    def _failure(self, operation, category, message, correlation_id=None, idempotency_key=None, status_code=None, attempts=1):
        return AdapterResult(None, attempts=attempts, provider=self.source, operation=operation, correlation_id=correlation_id, idempotency_key=idempotency_key, error_category=category, success=False, retryable=category in RETRYABLE_CATEGORIES, status_code=status_code, metadata={"providerId": self.provider_id, "safeMessage": message})

    def _validate_configuration(self):
        environment = str(self.config.get("environment", "SANDBOX")).upper()
        if environment not in {"SANDBOX", "PRODUCTION"}: return self._failure("health_check", "CONFIGURATION_ERROR", "Unsupported provider environment")
        try: references = auth_references(self.provider_id, self.config)
        except ValueError: return self._failure("health_check", "CONFIGURATION_ERROR", "Unsupported provider authentication configuration")
        if any(not os.getenv(reference) for reference in references.values() if reference): return self._failure("health_check", "CONFIGURATION_ERROR", "Provider authentication is not configured")
        endpoint_ref, endpoint = self.config.get("endpointRef"), None
        if endpoint_ref: endpoint = os.getenv(endpoint_ref)
        if environment == "PRODUCTION" and self.requires_endpoint:
            try: validate_endpoint(endpoint, environment)
            except ValueError: return self._failure("health_check", "CONFIGURATION_ERROR", "Production provider endpoint is not safely configured")
        elif endpoint:
            try: validate_endpoint(endpoint, environment)
            except ValueError: return self._failure("health_check", "CONFIGURATION_ERROR", "Provider endpoint is invalid")
        if str(self.config.get("authType", "NONE")).upper() == "OAUTH2_CLIENT_CREDENTIALS" and not self.config.get("accessTokenRef"):
            return self._failure("health_check", "UNSUPPORTED_OPERATION", "OAuth2 token exchange requires an approved runtime integration")
        return None

    def health_check(self, correlation_id=None):
        invalid = self._validate_configuration()
        if invalid: return {"status": "MISCONFIGURED" if invalid.error_category == "CONFIGURATION_ERROR" else "UNSUPPORTED", "providerId": self.provider_id, "provider": self.source, "adapterType": self.kind, "correlationId": correlation_id, "errorCategory": invalid.error_category}
        return {"status": "HEALTHY" if str(self.config.get("environment", "SANDBOX")).upper() == "PRODUCTION" else "AVAILABLE", "providerId": self.provider_id, "provider": self.source, "adapterType": self.kind, "correlationId": correlation_id}

    def discover(self, request: dict, **context): return self._failure("discover", "UNSUPPORTED_OPERATION", "Provider discovery is not configured", context.get("correlation_id"), context.get("idempotency_key"))
    def submit(self, request: dict, **context): return self._failure("submit", "UNSUPPORTED_OPERATION", "Provider submission is not configured", context.get("correlation_id"), context.get("idempotency_key"))
    def get_status(self, operation_id: str, **context): return self._failure("get_status", "UNSUPPORTED_OPERATION", "Provider status lookup is not configured", context.get("correlation_id"), context.get("idempotency_key"))
    def retrieve(self, request: Any, **context): return self._failure("retrieve", "UNSUPPORTED_OPERATION", "Provider retrieval is not configured", context.get("correlation_id"), context.get("idempotency_key"))
    def normalize(self, response: Any, **context): return response if isinstance(response, dict) else None


_SANDBOX_HANDLERS: dict[str, Callable] = {}


def register_sandbox_handler(name: str, fetcher: Callable) -> None: _SANDBOX_HANDLERS[name] = fetcher


def _load_sandbox_handlers() -> None:
    if _SANDBOX_HANDLERS: return
    from app.mocks import education_dept, revenue_dept, social_welfare_dept
    register_sandbox_handler("domicile_issue", revenue_dept.issue_domicile)
    register_sandbox_handler("income_fetch", revenue_dept.get_income)
    register_sandbox_handler("caste_fetch", social_welfare_dept.get_caste)
    register_sandbox_handler("bank_fetch", social_welfare_dept.get_bank_status)
    register_sandbox_handler("academic_fetch", education_dept.get_academic)


class AdapterFactory:
    _types = {"REST": "RestAPIAdapter", "REST API": "RestAPIAdapter", "SOAP": "LegacySOAPAdapter", "LEGACY SOAP WRAPPER": "LegacySOAPAdapter", "CSV": "CSVFileAdapter", "CSV/FILE ADAPTER": "CSVFileAdapter"}

    @classmethod
    def create(cls, adapter_type, provider_name, sandbox_handler=None, provider_id=None, config=None):
        _load_sandbox_handlers()
        adapter_class = globals().get(cls._types.get((adapter_type or "").strip().upper(), ""))
        if not adapter_class: return None
        configuration = config or {}
        fetcher = _SANDBOX_HANDLERS.get(sandbox_handler or "") if str(configuration.get("environment", "SANDBOX")).upper() == "SANDBOX" else None
        return adapter_class(provider_name, fetcher, provider_id=provider_id, config=configuration)


class SourceAdapter(ProviderAdapter):
    def _sandbox_call(self, citizen_id, operation, correlation_id=None, idempotency_key=None, simulate_timeout=False):
        if not self.fetcher: return self._failure(operation, "CONFIGURATION_ERROR", "Sandbox handler is not configured", correlation_id, idempotency_key)
        started = time.perf_counter()
        for attempt in range(1, int(self.config.get("maxAttempts", 3)) + 1):
            try:
                if simulate_timeout and attempt == 1: raise TimeoutError()
                normalized = self.normalize(self.fetcher(citizen_id))
                if normalized is None: raise AdapterError("Malformed provider response", "MALFORMED_RESPONSE")
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                _runtime_health[self.source] = {"lastSuccessAt": _now(), "lastResponseMs": elapsed, "errorCategory": None}
                return AdapterResult(normalized, attempts=attempt, delayed=attempt > 1, provider=self.source, operation=operation, correlation_id=correlation_id, idempotency_key=idempotency_key, response_ms=elapsed, success=True, metadata={"providerId": self.provider_id})
            except TimeoutError: category = "TIMEOUT"
            except ConnectionError: category = "NETWORK_ERROR"
            except AdapterError as error: category = error.category
            except Exception: category = "UPSTREAM_ERROR"
            _runtime_health[self.source] = {"lastFailureAt": _now(), "errorCategory": category}
            if category not in RETRYABLE_CATEGORIES or attempt >= int(self.config.get("maxAttempts", 3)):
                return self._failure(operation, category, "Sandbox provider operation failed", correlation_id, idempotency_key, attempts=attempt)
            time.sleep(0.08 * attempt)
        return self._failure(operation, "INTERNAL_ERROR", "Provider operation failed", correlation_id, idempotency_key)

    def _production_call(self, request): return self._failure(request.operation, "UNSUPPORTED_OPERATION", "Configured production transport is not implemented for this adapter", request.correlation_id, request.idempotency_key)
    def fetch(self, citizen_id, simulate_timeout=False, correlation_id=None, idempotency_key=None):
        result = self._sandbox_call(citizen_id, "retrieve", correlation_id, idempotency_key, simulate_timeout)
        return {"record": result.record, "attempts": result.attempts, "delayed": result.delayed, "queued": result.error_category in RETRYABLE_CATEGORIES and result.attempts >= int(self.config.get("maxAttempts", 3)), "adapter": self.kind, "correlationId": correlation_id, "idempotencyKey": idempotency_key, "errorCategory": result.error_category}
    def _execute(self, request, simulate_timeout=False):
        if str(self.config.get("environment", "SANDBOX")).upper() == "SANDBOX":
            return self._sandbox_call(request.data.get("citizenId", ""), request.operation, request.correlation_id, request.idempotency_key, simulate_timeout)
        result = self._production_call(request)
        for attempt in range(1, int(self.config.get("maxAttempts", 3)) + 1):
            result.attempts = attempt
            if result.success or not result.retryable or attempt >= int(self.config.get("maxAttempts", 3)): return result
            time.sleep(0.08 * attempt)
            result = self._production_call(request)
        return result
    def _request(self, operation, request, **context): return ProviderRequest(self.provider_id, operation, context.get("correlation_id"), context.get("idempotency_key"), {}, request if isinstance(request, dict) else {"citizenId": request})
    def discover(self, request, **context): return self._execute(self._request("discover", request, **context))
    def submit(self, request, **context): return self._execute(self._request("submit", request, **context))
    def get_status(self, operation_id, **context): return self._execute(self._request("get_status", {"operationId": operation_id}, **context))
    def retrieve(self, request, **context): return self._execute(self._request("retrieve", request, **context), context.get("simulate_timeout", False))


class RestAPIAdapter(SourceAdapter):
    kind = "REST API"

    def health_check(self, correlation_id=None):
        result = super().health_check(correlation_id)
        if result["status"] == "HEALTHY" and not self.config.get("endpointPath"):
            result.update({"status": "MISCONFIGURED", "errorCategory": "CONFIGURATION_ERROR"})
        return result

    def _auth_headers(self):
        auth_type, refs = str(self.config.get("authType", "NONE")).upper(), auth_references(self.provider_id, self.config)
        if auth_type == "API_KEY": return {self.config.get("apiKeyHeader", "X-API-Key"): os.environ[refs["apiKey"]]}
        if auth_type == "BASIC": return {"Authorization": "Basic " + base64.b64encode(f"{os.environ[refs['username']]}:{os.environ[refs['password']]}".encode()).decode()}
        if auth_type == "OAUTH2_CLIENT_CREDENTIALS": raise AdapterError("OAuth2 runtime exchange is not configured", "UNSUPPORTED_OPERATION")
        return {}

    def _production_call(self, request):
        invalid = self._validate_configuration()
        if invalid:
            invalid.operation, invalid.correlation_id, invalid.idempotency_key = request.operation, request.correlation_id, request.idempotency_key
            return invalid
        endpoint = os.getenv(self.config.get("endpointRef")) if self.config.get("endpointRef") else None
        path = self.config.get("endpointPath")
        if not endpoint or not path: return self._failure(request.operation, "CONFIGURATION_ERROR", "Production endpoint path is not configured", request.correlation_id, request.idempotency_key)
        try:
            url = validate_endpoint(endpoint.rstrip("/") + "/" + str(path).lstrip("/"), "PRODUCTION")
            headers = {"Accept": "application/json", "X-Correlation-ID": request.correlation_id or "", "Idempotency-Key": request.idempotency_key or ""}
            headers.update(self._auth_headers())
            body = json.dumps(request.data).encode() if request.operation in {"submit", "discover"} else None
            if body: headers["Content-Type"] = "application/json"
            started = time.perf_counter()
            with urlopen(Request(url, data=body, headers=headers, method="POST" if body else "GET"), timeout=min(max(int(self.config.get("timeoutSeconds", 5)), 1), 120)) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024: return self._failure(request.operation, "MALFORMED_RESPONSE", "Provider response exceeded the configured size limit", request.correlation_id, request.idempotency_key, response.status)
                normalized = self.normalize(json.loads(raw.decode("utf-8")))
                if normalized is None: return self._failure(request.operation, "MALFORMED_RESPONSE", "Provider response was not a JSON object", request.correlation_id, request.idempotency_key, response.status)
                return AdapterResult(normalized, provider=self.source, operation=request.operation, correlation_id=request.correlation_id, idempotency_key=request.idempotency_key, response_ms=round((time.perf_counter() - started) * 1000, 2), success=True, status_code=response.status, metadata={"providerId": self.provider_id})
        except HTTPError as error:
            category = "AUTHENTICATION_ERROR" if error.code == 401 else "AUTHORIZATION_ERROR" if error.code == 403 else "RATE_LIMITED" if error.code == 429 else "VALIDATION_ERROR" if 400 <= error.code < 500 else "UPSTREAM_ERROR"
            return self._failure(request.operation, category, "Configured provider returned an error", request.correlation_id, request.idempotency_key, error.code)
        except TimeoutError: return self._failure(request.operation, "TIMEOUT", "Configured provider timed out", request.correlation_id, request.idempotency_key)
        except URLError: return self._failure(request.operation, "NETWORK_ERROR", "Configured provider network call failed", request.correlation_id, request.idempotency_key)
        except json.JSONDecodeError: return self._failure(request.operation, "MALFORMED_RESPONSE", "Configured provider returned malformed data", request.correlation_id, request.idempotency_key)
        except AdapterError as error: return self._failure(request.operation, error.category, "Configured provider operation is not supported", request.correlation_id, request.idempotency_key)
        except Exception: return self._failure(request.operation, "INTERNAL_ERROR", "Provider operation failed safely", request.correlation_id, request.idempotency_key)


class LegacySOAPAdapter(SourceAdapter):
    kind = "Legacy SOAP Wrapper"

    def health_check(self, correlation_id=None):
        result = super().health_check(correlation_id)
        if result["status"] == "HEALTHY" and not self.config.get("wsdlRef"):
            result.update({"status": "UNSUPPORTED", "errorCategory": "UNSUPPORTED_OPERATION"})
        return result
    def _production_call(self, request):
        invalid = self._validate_configuration()
        if invalid:
            invalid.operation, invalid.correlation_id, invalid.idempotency_key = request.operation, request.correlation_id, request.idempotency_key
            return invalid
        return self._failure(request.operation, "UNSUPPORTED_OPERATION", "SOAP execution requires an approved WSDL contract", request.correlation_id, request.idempotency_key)


class CSVFileAdapter(SourceAdapter):
    kind = "CSV/File Adapter"
    requires_endpoint = False

    def health_check(self, correlation_id=None):
        result = super().health_check(correlation_id)
        if result["status"] == "HEALTHY" and not self.config.get("filePathRef"):
            result.update({"status": "MISCONFIGURED", "errorCategory": "CONFIGURATION_ERROR"})
        return result
    def _production_call(self, request):
        invalid = self._validate_configuration()
        if invalid:
            invalid.operation, invalid.correlation_id, invalid.idempotency_key = request.operation, request.correlation_id, request.idempotency_key
            return invalid
        path_value = os.getenv(self.config.get("filePathRef")) if self.config.get("filePathRef") else None
        root_value = os.getenv(self.config.get("allowedDirectoryRef")) if self.config.get("allowedDirectoryRef") else None
        if not path_value or not root_value: return self._failure(request.operation, "CONFIGURATION_ERROR", "Configured file source is incomplete", request.correlation_id, request.idempotency_key)
        path, root = Path(path_value).resolve(), Path(root_value).resolve()
        try: path.relative_to(root)
        except ValueError: return self._failure(request.operation, "VALIDATION_ERROR", "Configured file is outside the allowed directory", request.correlation_id, request.idempotency_key)
        if path.suffix.lower() != ".csv": return self._failure(request.operation, "VALIDATION_ERROR", "Configured file type is not supported", request.correlation_id, request.idempotency_key)
        try:
            if path.stat().st_size > 5 * 1024 * 1024: return self._failure(request.operation, "VALIDATION_ERROR", "Configured file exceeds the size limit", request.correlation_id, request.idempotency_key)
            with path.open("r", newline="", encoding="utf-8") as handle: rows = list(csv.DictReader(handle))
            if not rows: return self._failure(request.operation, "SCHEMA_MISMATCH", "Configured CSV schema is empty", request.correlation_id, request.idempotency_key)
            return AdapterResult(self.normalize(rows[0]), provider=self.source, operation=request.operation, correlation_id=request.correlation_id, idempotency_key=request.idempotency_key, success=True, metadata={"providerId": self.provider_id})
        except (OSError, UnicodeError, csv.Error): return self._failure(request.operation, "MALFORMED_RESPONSE", "Configured CSV could not be parsed", request.correlation_id, request.idempotency_key)


def request_registered_service(service_id, citizen_id, requirement_code=None, correlation_id=None, idempotency_key=None):
    from sqlalchemy.orm import Session
    from app.core.persistence import ProviderCapabilityRow, ProviderRow, ServiceCatalogRow, engine
    with Session(engine) as session:
        service = session.get(ServiceCatalogRow, service_id)
    selected_requirement = requirement_code or (service.requirement_code if service else None)
    from app.engine.registry import select_dependency_provider
    selected = select_dependency_provider(selected_requirement, integration_health()) if service and selected_requirement else None
    if not selected or selected.get("serviceId") != service_id:
        return AdapterResult(None, provider=None, correlation_id=correlation_id, idempotency_key=idempotency_key, error_category="CONFIGURATION_ERROR", success=False)
    with Session(engine) as session:
        service = session.get(ServiceCatalogRow, service_id)
        capability = session.query(ProviderCapabilityRow).filter(
            ProviderCapabilityRow.service_id == service.service_id if service else False,
            ProviderCapabilityRow.provider_id == service.provider_id if service else False,
            ProviderCapabilityRow.capability_code == (requirement_code or service.requirement_code) if service else False,
            ProviderCapabilityRow.enabled.is_(True),
        ).first() if service else None
        provider = session.query(ProviderRow).filter_by(provider_id=service.provider_id, active=True).first() if capability and service.active else None
    if not service or not capability or not provider: return AdapterResult(None, provider=None, correlation_id=correlation_id, idempotency_key=idempotency_key, error_category="CONFIGURATION_ERROR", success=False)
    health = next((item for item in integration_health() if item.get("providerId") == provider.provider_id or item.get("system") == provider.name), None)
    if not health or health.get("status") not in {"AVAILABLE", "HEALTHY"}:
        return AdapterResult(None, provider=provider.name, correlation_id=correlation_id, idempotency_key=idempotency_key, error_category="UPSTREAM_UNAVAILABLE", success=False, retryable=True, metadata={"providerId": provider.provider_id})
    handler_name = service.payload.get("sandboxHandler") or provider.payload.get("sandboxHandler")
    config = {**(provider.payload or {}), "providerId": provider.provider_id, "environment": provider.environment, "authType": provider.auth_type, "endpointRef": provider.endpoint_ref, "timeoutSeconds": provider.timeout_seconds, "maxAttempts": provider.max_attempts}
    adapter = AdapterFactory.create(provider.adapter_type, provider.name, handler_name, provider_id=provider.provider_id, config=config)
    if not adapter: return AdapterResult(None, provider=provider.name, correlation_id=correlation_id, idempotency_key=idempotency_key, error_category="UNSUPPORTED_OPERATION", success=False, metadata={"providerId": provider.provider_id})
    return adapter.retrieve({"citizenId": citizen_id}, correlation_id=correlation_id, idempotency_key=idempotency_key or f"{service_id}:{citizen_id}")


def fetch_registered_service(service_id, citizen_id): return request_registered_service(service_id, citizen_id).record
def service_available(provider): return is_integration_available(provider)


def set_integration_availability(source, available, error=None):
    if source not in _configured_integrations(): raise KeyError(f"Unknown integration: {source}")
    _availability[source] = {"available": available, "error": error if not available else None}
    return next(item for item in integration_health(record_event=True) if item["system"] == source)


def is_integration_available(source): return _availability.get(source, {"available": True})["available"]


def integration_health(record_event=False):
    result = []
    for system, metadata in _configured_integrations().items():
        state = _availability.get(system, {"available": True, "error": None})
        config = {**metadata, "providerId": metadata.get("providerId", system)}
        adapter = AdapterFactory.create(metadata.get("adapterType", ""), system, metadata.get("payload", {}).get("sandboxHandler"), provider_id=config["providerId"], config=config)
        checked = adapter.health_check() if adapter else {"status": "UNSUPPORTED", "errorCategory": "UNSUPPORTED_OPERATION"}
        runtime = _runtime_health.get(system, {})
        status = "UNAVAILABLE" if not state["available"] else checked.get("status", "UNSUPPORTED")
        if status in {"AVAILABLE", "HEALTHY"} and runtime.get("lastFailureAt") and runtime.get("errorCategory"):
            status = "DEGRADED"
        item = {"system": system, "department": system, "adapterType": metadata.get("adapterType"), "service": metadata.get("service"), "status": status, "lastCheckedAt": _now(), "error": "Provider unavailable" if status == "UNAVAILABLE" else None, "lastSuccessAt": runtime.get("lastSuccessAt"), "lastFailureAt": runtime.get("lastFailureAt"), "errorCategory": runtime.get("errorCategory") or checked.get("errorCategory"), "lastResponseMs": runtime.get("lastResponseMs")}
        result.append(item)
        if record_event and _last_health.get(system) != status:
            event_bus.publish("INTEGRATION_HEALTH_CHANGED", {"system": system, "status": status, "service": metadata.get("service")})
            audit_bus.append("SYSTEM", "INTEGRATION_HEALTH", "Integration availability check", system, status, payload={"system": system, "status": status})
        _last_health[system] = status
    return result


def validate_payload(record):
    if not record: return {"valid": False, "reasons": ["No source record available"]}
    reasons = []
    if not record.get("signature"): reasons.append("Missing source signature")
    if not record.get("validUntil"): reasons.append("Missing validity period")
    return {"valid": not reasons, "reasons": reasons}
