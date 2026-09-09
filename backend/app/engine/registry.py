from __future__ import annotations

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
}]


# Deterministic service catalog for prototype dependency selection. The adapter
# names and action identifiers point to the existing mock integrations.
DEPENDENCY_SERVICES = [
    {
        "requirementCode": "DOMICILE_PROOF", "requiredService": "Domicile Certificate",
        "serviceName": "Domicile Issuance", "provider": "Revenue Department",
        "adapter": "REST API", "serviceId": "REV-MAHA-101",
        "reason": "Provider registered for required canonical service",
    },
    {
        "requirementCode": "ACADEMIC_RECORD", "requiredService": "Academic Record",
        "serviceName": "Academic Verification", "provider": "Education Department",
        "adapter": "CSV/File Adapter", "serviceId": "EDU-ACA-201",
        "reason": "Provider registered for required canonical service",
    },
]


def get_scheme(scheme_id: str):
    return next((s for s in SCHEMES if s["id"] == scheme_id), None)


def dependency_registry(health: list[dict]) -> list[dict]:
    health_by_provider = {item["system"]: item for item in health}
    return [{**definition, "healthStatus": health_by_provider.get(definition["provider"], {}).get("status", "UNAVAILABLE")} for definition in DEPENDENCY_SERVICES]


def select_dependency_provider(requirement_code: str, health: list[dict]) -> dict | None:
    candidates = [item for item in dependency_registry(health) if item["requirementCode"] == requirement_code]
    if not candidates:
        return None
    # Stable registry order is the tie-breaker after availability.
    return sorted(candidates, key=lambda item: (item["healthStatus"] != "AVAILABLE", item["provider"]))[0]
