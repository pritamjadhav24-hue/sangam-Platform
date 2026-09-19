"""Small structured logging boundary with a strict non-sensitive field set."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_logger = logging.getLogger("sangam.operations")


def structured_log(event_name: str, level: str = "INFO", **fields) -> dict:
    allowed = {
        "correlation_id", "application_id", "dependency_id", "job_id", "provider_id",
        "worker_id", "duration_ms", "outcome", "status", "error_category", "attempt",
        "max_attempts", "operation", "queue", "worker_status",
    }
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level.upper(), "event": event_name}
    record.update({key: value for key, value in fields.items() if key in allowed and value is not None})
    message = json.dumps(record, separators=(",", ":"), default=str)
    getattr(_logger, level.lower(), _logger.info)(message)
    return record
