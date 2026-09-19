"""Centralized minimization/redaction rules for operational data boundaries."""
from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_TERMS = (
    "password", "token", "access_token", "refresh_token", "authorization",
    "api_key", "apikey", "client_secret", "secret", "credential", "jwt",
    "aadhaar", "pan", "dob", "phone", "email", "address", "bank",
    "account", "document", "raw_response", "response_body",
)


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(term in normalized for term in SENSITIVE_KEY_TERMS)


def redact(value: Any, *, replacement: str = "[REDACTED]") -> Any:
    """Recursively redact sensitive fields while retaining safe operational metadata."""
    if isinstance(value, dict):
        return {key: replacement if is_sensitive_key(key) else redact(child, replacement=replacement) for key, child in value.items()}
    if isinstance(value, list):
        return [redact(child, replacement=replacement) for child in value]
    if isinstance(value, tuple):
        return tuple(redact(child, replacement=replacement) for child in value)
    return value


def safe_error_message(error: Any) -> str:
    """Keep error categories useful without returning upstream bodies or secrets."""
    message = str(error or "")
    message = re.sub(r"(?is)(password|token|authorization|api[_-]?key|client[_-]?secret|secret|credential)\s*[=:]\s*[^,;\s]+", r"\1=[REDACTED]", message)
    if any(term in message.lower() for term in ("traceback", "sqlalchemy", "psycopg", "redis", "http response body")):
        return "Upstream operation failed."
    return message[:240] or "Upstream operation failed."
