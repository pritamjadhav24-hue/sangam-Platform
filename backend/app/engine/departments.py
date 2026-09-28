"""Which government department a provider belongs to, and how to name it.

A provider served by a department's own API is identified by its API path
(``/departments/<department>/...``); the few providers that are not department
APIs are listed explicitly. Used for the citizen's "Source: Revenue
Department" line and for grouping provider health per department in Admin.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

# key -> (English, Marathi, headline department shown first in Admin)
DEPARTMENTS: dict[str, tuple[str, str, bool]] = {
    "REVENUE": ("Revenue Department", "महसूल विभाग", True),
    "EDUCATION": ("Education Department", "शिक्षण विभाग", True),
    "SOCIAL_WELFARE": ("Social Welfare Department", "समाज कल्याण विभाग", True),
    "MUNICIPAL_HEALTH": ("Health Department", "आरोग्य विभाग", True),
    "TRANSPORT": ("Transport Department", "परिवहन विभाग", True),
    "AGRICULTURE": ("Agriculture Department", "कृषी विभाग", False),
    "LABOUR": ("Labour Department", "कामगार विभाग", False),
    "FOOD_CIVIL_SUPPLIES": ("Food & Civil Supplies Department", "अन्न व नागरी पुरवठा विभाग", False),
    "HOUSING": ("Housing Department", "गृहनिर्माण विभाग", False),
    "SKILL_EMPLOYMENT": ("Skill Development & Employment Department", "कौशल्य विकास व रोजगार विभाग", False),
    "IDENTITY": ("State Resident Registry", "राज्य रहिवासी नोंदणी", False),
    "DBT": ("Direct Benefit Transfer Registry", "थेट लाभ हस्तांतरण नोंदणी", False),
}

# Providers that are not a department API (no /departments/<key>/ path).
_NON_API_PROVIDERS = {
    "REVENUE-DEPARTMENT": "REVENUE", "EDUCATION-DEPARTMENT": "EDUCATION", "SOCIAL-WELFARE-DEPARTMENT": "SOCIAL_WELFARE",
    "AUTHORIZED-DBT": "DBT", "STATE-RESIDENT-REGISTRY": "IDENTITY",
}


def department_label(key: Optional[str], language: str = "en") -> Optional[str]:
    if not key or key not in DEPARTMENTS:
        return None
    english, marathi, _ = DEPARTMENTS[key]
    return marathi if language == "mr" else english


@lru_cache(maxsize=256)
def provider_department(provider_id: Optional[str]) -> Optional[str]:
    """Department key for a provider id (cached: the mapping is static)."""
    if not provider_id:
        return None
    if provider_id in _NON_API_PROVIDERS:
        return _NON_API_PROVIDERS[provider_id]
    from sqlalchemy.orm import Session
    from app.core.persistence import ProviderRow, engine
    from app.engine.adapters import department_key_from_path
    with Session(engine) as session:
        provider = session.get(ProviderRow, provider_id)
        http_path = (provider.payload or {}).get("httpPath") if provider else None
    return department_key_from_path(http_path)
