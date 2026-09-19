from __future__ import annotations

import os


class CatalogConfigurationError(RuntimeError):
    """The authoritative catalog could not be read or is incomplete."""


def _demo_fallback_enabled() -> bool:
    return os.getenv("SANGAM_ENV", "development").strip().lower() not in {"production", "prod"} and os.getenv("SANGAM_ALLOW_DEMO_FALLBACK", "false").lower() in {"1", "true", "yes"}

SCHEMES = [{
    "id": "SCH-MH-2026", "name": "Post-Matric Higher Education Scholarship",
    "nameMr": "माध्यमिकोत्तर उच्च शिक्षण शिष्यवृत्ती", "department": "Higher Education Department",
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "INCOME_PROOF", "label": "Income proof", "mandatory": True},
        {"code": "CASTE_PROOF", "label": "Caste proof", "mandatory": True},
        {"code": "DOMICILE_PROOF", "label": "Maharashtra domicile", "mandatory": True},
        {"code": "ACADEMIC_RECORD", "label": "Academic record", "mandatory": True},
        {"code": "BANK_DETAILS", "label": "DBT bank status", "mandatory": True},
    ],
}, {
    "id": "EDU-ACADEMIC-2026", "name": "Academic Record Verification",
    "nameMr": "शैक्षणिक नोंद पडताळणी", "department": "Education Department",
    "requirements": [
        {"code": "IDENTITY", "label": "Identity", "mandatory": True},
        {"code": "ACADEMIC_RECORD", "label": "Academic record", "mandatory": True},
    ],
}]


# Development fallback catalog. Production selection reads the PostgreSQL catalog.
DEPENDENCY_SERVICES = [
    {
        "requirementCode": "INCOME_PROOF", "requiredService": "Income Verification",
        "serviceName": "Income Verification", "provider": "Revenue Department",
        "adapter": "REST API", "serviceId": "REV-INCOME-102", "sandboxHandler": "income_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "CASTE_PROOF", "requiredService": "Caste Verification",
        "serviceName": "Caste Verification", "provider": "Social Welfare Department",
        "adapter": "Legacy SOAP Wrapper", "serviceId": "SW-CASTE-301", "sandboxHandler": "caste_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "DOMICILE_PROOF", "requiredService": "Domicile Certificate",
        "serviceName": "Domicile Issuance", "provider": "Revenue Department",
        "adapter": "REST API", "serviceId": "REV-MAHA-101", "sandboxHandler": "domicile_issue", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "ACADEMIC_RECORD", "requiredService": "Academic Record",
        "serviceName": "Academic Verification", "provider": "Education Department",
        "adapter": "CSV/File Adapter", "serviceId": "EDU-ACA-201", "sandboxHandler": "academic_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "BANK_DETAILS", "requiredService": "Bank Status",
        "serviceName": "DBT Account Verification", "provider": "Authorized DBT",
        "adapter": "REST API", "serviceId": "DBT-BANK-401", "sandboxHandler": "bank_fetch", "priority": 10, "timeoutSeconds": 5, "maxAttempts": 3,
        "reason": "Provider registered for required canonical service",
    },
]


def get_scheme(scheme_id: str):
    try:
        from app.core.persistence import catalog_snapshot
        configured = catalog_snapshot()["schemes"]
    except Exception as error:
        if not _demo_fallback_enabled():
            raise CatalogConfigurationError("Configured service catalog is unavailable") from error
        configured = []
    if not configured and not _demo_fallback_enabled():
        return None
    return next((s for s in (configured or SCHEMES) if s["id"] == scheme_id), None)


def dependency_registry(health: list[dict]) -> list[dict]:
    try:
        from app.core.persistence import provider_capability_snapshot
        definitions = provider_capability_snapshot()
    except Exception as error:
        if not _demo_fallback_enabled():
            raise CatalogConfigurationError("Provider capability catalog is unavailable") from error
        definitions = []
    if not definitions:
        if not _demo_fallback_enabled():
            return []
        definitions = DEPENDENCY_SERVICES
    health_by_provider = {}
    for item in health:
        for key in (item.get("system"), item.get("provider"), item.get("providerId")):
            if key:
                health_by_provider[key] = item
    return [{**definition, "healthStatus": health_by_provider.get(definition.get("providerId"), health_by_provider.get(definition.get("provider"), {})).get("status", "UNAVAILABLE")} for definition in definitions]


def select_dependency_provider(requirement_code: str, health: list[dict]) -> dict | None:
    candidates = [item for item in dependency_registry(health) if item["requirementCode"] == requirement_code]
    eligible = [item for item in candidates if item.get("healthStatus") in {"AVAILABLE", "HEALTHY"}]
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (item.get("priority", 100), item["provider"]))[0]
