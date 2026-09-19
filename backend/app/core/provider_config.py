"""Non-secret provider configuration and environment secret references."""
from __future__ import annotations

import os
import re
import ipaddress
from urllib.parse import urlparse


def _env_key(provider_id: str, field: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9]", "_", provider_id).upper()
    return f"PROVIDER_{safe_id}_{field.upper()}"


def provider_runtime_config(provider_id: str, metadata: dict | None = None) -> dict:
    """Return safe runtime metadata; secret values are intentionally omitted."""
    metadata = metadata or {}
    endpoint_ref = metadata.get("endpointRef") or _env_key(provider_id, "BASE_URL")
    endpoint = os.getenv(endpoint_ref)
    auth_type = (metadata.get("authType") or "NONE").upper()
    references = auth_references(provider_id, metadata)
    auth_configured = auth_type == "NONE" or all(bool(os.getenv(reference)) for reference in references.values() if reference)
    return {
        "providerId": provider_id,
        "endpointConfigured": bool(endpoint),
        "endpointRef": endpoint_ref,
        "authType": auth_type,
        "authConfigured": auth_configured,
        "authReferences": references,
        "clientIdConfigured": bool(os.getenv(references.get("clientId") or metadata.get("clientIdRef") or _env_key(provider_id, "CLIENT_ID"))),
        "clientSecretConfigured": bool(os.getenv(references.get("clientSecret") or metadata.get("clientSecretRef") or _env_key(provider_id, "CLIENT_SECRET"))),
        "timeoutSeconds": min(max(int(metadata.get("timeoutSeconds", 5)), 1), 120),
        "maxAttempts": min(max(int(metadata.get("maxAttempts", 3)), 1), 5),
    }


def auth_references(provider_id: str, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    auth_type = (metadata.get("authType") or "NONE").upper()
    if auth_type == "API_KEY":
        return {"apiKey": metadata.get("apiKeyRef") or _env_key(provider_id, "API_KEY")}
    if auth_type == "BASIC":
        return {"username": metadata.get("usernameRef") or _env_key(provider_id, "USERNAME"), "password": metadata.get("passwordRef") or _env_key(provider_id, "PASSWORD")}
    if auth_type == "OAUTH2_CLIENT_CREDENTIALS":
        return {"clientId": metadata.get("clientIdRef") or _env_key(provider_id, "CLIENT_ID"), "clientSecret": metadata.get("clientSecretRef") or _env_key(provider_id, "CLIENT_SECRET"), "tokenUrl": metadata.get("tokenUrlRef") or _env_key(provider_id, "TOKEN_URL")}
    if auth_type != "NONE":
        raise ValueError(f"Unsupported provider authentication type: {auth_type}")
    return {}


def validate_endpoint(endpoint: str | None, environment: str = "SANDBOX") -> str:
    if not endpoint:
        raise ValueError("Provider endpoint is not configured")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Provider endpoint must be an absolute HTTP(S) URL")
    host = parsed.hostname.lower()
    is_private = host in {"localhost", "127.0.0.1", "::1"}
    try:
        is_private = is_private or ipaddress.ip_address(host).is_private
    except ValueError:
        pass
    if environment.upper() == "PRODUCTION" and (parsed.scheme != "https" or is_private):
        raise ValueError("Production provider endpoints must use public HTTPS")
    return endpoint
