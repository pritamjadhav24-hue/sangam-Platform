import time
from typing import Callable


class SourceAdapter:
    kind = "REST"
    def __init__(self, source: str, fetcher: Callable): self.source, self.fetcher = source, fetcher
    def fetch(self, citizen_id: str, simulate_timeout: bool = False):
        for attempt in range(1, 4):
            try:
                if simulate_timeout and attempt == 1:
                    raise TimeoutError("Upstream response timeout")
                record = self.fetcher(citizen_id)
                return {"record": record, "attempts": attempt, "delayed": attempt > 1, "adapter": self.kind}
            except TimeoutError:
                if attempt == 3: return {"record": None, "attempts": attempt, "delayed": True, "queued": True, "adapter": self.kind}
                time.sleep(0.08 * attempt)


class RestAPIAdapter(SourceAdapter): kind = "REST API"
class LegacySOAPAdapter(SourceAdapter): kind = "Legacy SOAP Wrapper"
class CSVFileAdapter(SourceAdapter): kind = "CSV/File Adapter"


def validate_payload(record: dict | None) -> dict:
    if not record: return {"valid": False, "reasons": ["No source record available"]}
    reasons = []
    if not record.get("signature"): reasons.append("Missing source signature")
    if not record.get("validUntil"): reasons.append("Missing validity period")
    return {"valid": not reasons, "reasons": reasons}
