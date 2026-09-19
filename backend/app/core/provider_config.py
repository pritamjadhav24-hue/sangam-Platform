"""Non-secret provider configuration and environment secret references."""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse


def _env_key(provider_id: str, field: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9]", "_", provider_id).upper()
    return f"PROVIDER_{safe_id}_{field.upper()}"


def provider_runtime_config(provider_id: str, metadata: dict | None = None) -> dict:
    """Return safe runtime metadata; secret values are intentionally omitted."""
    metadata = metadata or {}
    endpoint_ref = metadata.get("endpointRef") or _env_key(provider_id, "BASE_URL")
    endpoint = os.getenv(endpoint_ref)
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid endpoint configured for provider {provider_id}")
    return {
        "providerId": provider_id,
        "endpointConfigured": bool(endpoint),
        "endpointRef": endpoint_ref,
        "clientIdConfigured": bool(os.getenv(metadata.get("clientIdRef") or _env_key(provider_id, "CLIENT_ID"))),
        "clientSecretConfigured": bool(os.getenv(metadata.get("clientSecretRef") or _env_key(provider_id, "CLIENT_SECRET"))),
        "timeoutSeconds": min(max(int(metadata.get("timeoutSeconds", 5)), 1), 120),
        "maxAttempts": min(max(int(metadata.get("maxAttempts", 3)), 1), 5),
    }
