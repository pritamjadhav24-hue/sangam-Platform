from __future__ import annotations

import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable

from app.core.audit_bus import audit_bus
from app.core.event_bus import event_bus


_availability = {}
_last_health = {}
_runtime_health = {}
_integrations = {
    "Civil Registry": {"adapterType": "Federated SSO", "service": "Identity verification"},
    "Revenue Department": {"adapterType": "REST API", "service": "Income and domicile services"},
    "Social Welfare Department": {"adapterType": "Legacy SOAP Wrapper", "service": "Caste verification"},
    "Education Department": {"adapterType": "CSV/File Adapter", "service": "Academic records"},
    "Authorized DBT": {"adapterType": "REST API", "service": "Bank account verification"},
}


def _configured_integrations() -> dict:
    """Load provider health metadata from PostgreSQL, with test-only fallback."""
    configured = {}
    try:
        from sqlalchemy.orm import Session
        from app.core.persistence import ProviderRow, ServiceCatalogRow, engine
        with Session(engine) as session:
            for provider in session.query(ProviderRow).filter_by(active=True).all():
                service = session.query(ServiceCatalogRow).filter_by(provider_id=provider.provider_id, active=True).first()
                configured[provider.name] = {"adapterType": provider.adapter_type, "service": service.name if service else "Configured provider service", "providerId": provider.provider_id, "payload": provider.payload}
    except Exception:
        configured = {}
    return configured or _integrations


def request_registered_service(service_id: str, citizen_id: str, correlation_id: str | None = None, idempotency_key: str | None = None) -> AdapterResult:
    """Stable provider contract used by orchestration.

    Real adapters can register the same service-id contract. The current
    development registrations are deliberately kept behind this boundary.
    """
    from sqlalchemy.orm import Session
    from app.core.persistence import ProviderRow, ServiceCatalogRow, engine
    with Session(engine) as session:
        service = session.get(ServiceCatalogRow, service_id)
        provider = session.get(ProviderRow, service.provider_id) if service else None
    if not service or not provider:
        return AdapterResult(None, provider=None, correlation_id=correlation_id, idempotency_key=idempotency_key)
    handler_name = service.payload.get("sandboxHandler") or provider.payload.get("sandboxHandler")
    adapter = AdapterFactory.create(provider.adapter_type, provider.name, handler_name)
    if not adapter:
        return AdapterResult(None, provider=provider.name, correlation_id=correlation_id, idempotency_key=idempotency_key)
    return adapter.retrieve(citizen_id, correlation_id=correlation_id, idempotency_key=idempotency_key or f"{service_id}:{citizen_id}")


def fetch_registered_service(service_id: str, citizen_id: str) -> dict | None:
    return request_registered_service(service_id, citizen_id).record


def service_available(provider: str) -> bool:
    return is_integration_available(provider)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_integration_availability(source: str, available: bool, error: str | None = None) -> dict:
    if source not in _configured_integrations():
        raise KeyError(f"Unknown integration: {source}")
    _availability[source] = {"available": available, "error": error if not available else None}
    snapshot = integration_health(record_event=True)
    return next(item for item in snapshot if item["system"] == source)


def is_integration_available(source: str) -> bool:
    return _availability.get(source, {"available": True})["available"]


def integration_health(record_event: bool = False) -> list[dict]:
    checked_at = _now()
    result = []
    for system, metadata in _configured_integrations().items():
        state = _availability.get(system, {"available": True, "error": None})
        status = "AVAILABLE" if state["available"] else "UNAVAILABLE"
        item = {
            "system": system,
            "department": system,
            "adapterType": metadata["adapterType"],
            "service": metadata["service"],
            "status": status,
            "lastCheckedAt": checked_at,
            "error": state.get("error"),
            "lastSuccessAt": _runtime_health.get(system, {}).get("lastSuccessAt"),
            "lastFailureAt": _runtime_health.get(system, {}).get("lastFailureAt"),
            "errorCategory": _runtime_health.get(system, {}).get("errorCategory"),
            "lastResponseMs": _runtime_health.get(system, {}).get("lastResponseMs"),
        }
        result.append(item)
        if record_event and _last_health.get(system) != status:
            event_bus.publish("INTEGRATION_HEALTH_CHANGED", {"system": system, "status": status, "service": metadata["service"]})
            audit_bus.append("SYSTEM", "INTEGRATION_HEALTH", "Integration availability check", system, status, payload={"system": system, "status": status})
        _last_health[system] = status
    return result


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


class AdapterError(Exception):
    def __init__(self, message: str, category: str = "PERMANENT", transient: bool = False):
        super().__init__(message)
        self.category = category
        self.transient = transient


class ProviderAdapter:
    """Production integration contract implemented by REST/SOAP/file adapters."""
    kind = "GENERIC"

    def health_check(self, correlation_id: str | None = None) -> dict:
        return {"status": "AVAILABLE", "provider": getattr(self, "source", None), "correlationId": correlation_id}

    def discover(self, request: dict, **context) -> AdapterResult:
        raise NotImplementedError

    def submit(self, request: dict, **context) -> AdapterResult:
        return self.discover(request, **context)

    def get_status(self, operation_id: str, **context) -> AdapterResult:
        raise NotImplementedError

    def retrieve(self, request: Any, **context) -> AdapterResult:
        return self.discover({"citizenId": request} if isinstance(request, str) else request, **context)

    def normalize(self, response: Any, **context) -> dict | None:
        return response if isinstance(response, dict) else None


_SANDBOX_HANDLERS: dict[str, Callable] = {}


def register_sandbox_handler(name: str, fetcher: Callable) -> None:
    """Register development behavior by configuration name, not provider ID."""
    _SANDBOX_HANDLERS[name] = fetcher


def _load_sandbox_handlers() -> None:
    if _SANDBOX_HANDLERS:
        return
    from app.mocks import education_dept, revenue_dept, social_welfare_dept
    register_sandbox_handler("domicile_issue", revenue_dept.issue_domicile)
    register_sandbox_handler("income_fetch", revenue_dept.get_income)
    register_sandbox_handler("caste_fetch", social_welfare_dept.get_caste)
    register_sandbox_handler("bank_fetch", social_welfare_dept.get_bank_status)
    register_sandbox_handler("academic_fetch", education_dept.get_academic)


class AdapterFactory:
    """Creates adapters from protocol/type configuration."""
    _types = {
        "REST": "RestAPIAdapter",
        "REST API": "RestAPIAdapter",
        "SOAP": "LegacySOAPAdapter",
        "LEGACY SOAP WRAPPER": "LegacySOAPAdapter",
        "CSV": "CSVFileAdapter",
        "CSV/FILE ADAPTER": "CSVFileAdapter",
    }

    @classmethod
    def create(cls, adapter_type: str, provider_name: str, sandbox_handler: str | None = None) -> ProviderAdapter | None:
        _load_sandbox_handlers()
        normalized = (adapter_type or "").strip().upper()
        adapter_class = globals().get(cls._types.get(normalized, ""))
        fetcher = _SANDBOX_HANDLERS.get(sandbox_handler or "")
        if not adapter_class or not fetcher:
            return None
        return adapter_class(provider_name, fetcher)


class SourceAdapter(ProviderAdapter):
    kind = "REST"
    def __init__(self, source: str, fetcher: Callable):
        self.source, self.fetcher = source, fetcher
        _integrations.setdefault(source, {"adapterType": self.kind, "service": "Mock adapter service"})
    def _call(self, citizen_id: str, simulate_timeout: bool = False, **context) -> AdapterResult:
        started = time.perf_counter()
        if simulate_timeout:
            raise AdapterError("Upstream response timeout", "TIMEOUT", transient=True)
        try:
            record = self.fetcher(citizen_id)
        except TimeoutError as error:
            raise AdapterError(str(error), "TIMEOUT", transient=True) from error
        except ConnectionError as error:
            raise AdapterError(str(error), "NETWORK", transient=True) from error
        except Exception as error:
            raise AdapterError(str(error), "UPSTREAM", transient=False) from error
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return AdapterResult(self.normalize(record), provider=self.source, operation=context.get("operation", "retrieve"), correlation_id=context.get("correlation_id"), idempotency_key=context.get("idempotency_key"), response_ms=elapsed)

    def fetch(self, citizen_id: str, simulate_timeout: bool = False, correlation_id: str | None = None, idempotency_key: str | None = None):
        for attempt in range(1, 4):
            try:
                result = self._call(citizen_id, simulate_timeout and attempt == 1, correlation_id=correlation_id, idempotency_key=idempotency_key)
                result.attempts = attempt
                result.delayed = attempt > 1
                _runtime_health[self.source] = {"lastSuccessAt": _now(), "lastResponseMs": result.response_ms, "errorCategory": None}
                return {"record": result.record, "attempts": attempt, "delayed": result.delayed, "adapter": self.kind, "correlationId": correlation_id, "idempotencyKey": idempotency_key}
            except AdapterError as error:
                _runtime_health[self.source] = {"lastFailureAt": _now(), "errorCategory": error.category}
                if not error.transient:
                    return {"record": None, "attempts": attempt, "delayed": attempt > 1, "adapter": self.kind, "errorCategory": error.category}
                if attempt == 3: return {"record": None, "attempts": attempt, "delayed": True, "queued": True, "adapter": self.kind}
                time.sleep(0.08 * attempt)

    def discover(self, request: dict, **context) -> AdapterResult:
        result = self.fetch(request["citizenId"], correlation_id=context.get("correlation_id"), idempotency_key=context.get("idempotency_key"))
        return AdapterResult(result.get("record"), result.get("attempts", 1), result.get("delayed", False), result.get("queued", False), self.source, "discover", context.get("correlation_id"), context.get("idempotency_key"))

    def retrieve(self, request: Any, **context) -> AdapterResult:
        result = self.fetch(request if isinstance(request, str) else request["citizenId"], correlation_id=context.get("correlation_id"), idempotency_key=context.get("idempotency_key"))
        return AdapterResult(result.get("record"), result.get("attempts", 1), result.get("delayed", False), result.get("queued", False), self.source, "retrieve", context.get("correlation_id"), context.get("idempotency_key"))

    def get_status(self, operation_id: str, **context) -> AdapterResult:
        return AdapterResult({"operationId": operation_id, "status": "UNKNOWN"}, provider=self.source, operation="get_status")


class RestAPIAdapter(SourceAdapter): kind = "REST API"
class LegacySOAPAdapter(SourceAdapter): kind = "Legacy SOAP Wrapper"
class CSVFileAdapter(SourceAdapter): kind = "CSV/File Adapter"


def validate_payload(record: dict | None) -> dict:
    if not record: return {"valid": False, "reasons": ["No source record available"]}
    reasons = []
    if not record.get("signature"): reasons.append("Missing source signature")
    if not record.get("validUntil"): reasons.append("Missing validity period")
    return {"valid": not reasons, "reasons": reasons}
