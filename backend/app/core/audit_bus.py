from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any


class AuditBus:
    """Append-only hash-chained ledger. Payloads are represented only by their hash."""
    def __init__(self):
        self.entries: list[dict[str, Any]] = []
        self._processed_event_ids: set[str] = set()
        # Phase 6D: concurrent Auto-Fill requests for different requirements
        # run on separate threads (FastAPI's threadpool for sync handlers),
        # each calling audit_bus.append(). "sequence" and "previousHash" are
        # both derived from self.entries' current length/tail, so two
        # concurrent appends can read the same snapshot and both try to
        # allocate the same sequence number -- the Postgres persistence
        # layer's sequence primary key then rejects the second write with a
        # duplicate-key error, turning an otherwise-successful request into
        # a spurious failure. A single process-wide lock serializes the
        # (tiny, non-blocking) read-allocate-append critical section without
        # changing the ledger's shape or semantics.
        self._lock = threading.Lock()
        # Highest sequence number known to be allocated -- in this process or
        # in the persisted ledger.  Sequences come from this high-water mark,
        # never from len(self.entries): the persisted ledger can have gaps
        # (the legacy snapshot is last-writer-wins across the API process,
        # the worker and reloads), and after hydrating N rows with gaps,
        # len + 1 re-issues a sequence that is already in use.
        self._last_sequence = 0

    def _hash(self, entry: dict[str, Any]) -> str:
        content = {k: v for k, v in entry.items() if k != "entryHash"}
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _next_sequence(self) -> int:
        # Caller holds self._lock.
        tail = self.entries[-1]["sequence"] if self.entries else 0
        self._last_sequence = max(self._last_sequence, tail) + 1
        return self._last_sequence

    def append(self, who: str, what: str, why: str, source: str, action: str,
               consent_id: str | None = None, payload: Any = None,
               correlation_id: str | None = None) -> dict[str, Any]:
        # Keep citizen identifiers out of the append-only audit projection while
        # retaining a stable actor reference for investigations.
        if str(who).startswith("CITIZEN_"):
            who = "CITIZEN_REF-" + hashlib.sha256(str(who).encode()).hexdigest()[:12].upper()
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        with self._lock:
            previous_hash = self.entries[-1]["entryHash"] if self.entries else "GENESIS"
            entry = {
                "sequence": self._next_sequence(), "who": who, "what": what, "why": why,
                "when": datetime.now(timezone.utc).isoformat(), "source": source, "action": action,
                "consentId": consent_id, "correlationId": correlation_id,
                "payloadHash": payload_hash, "previousHash": previous_hash,
            }
            entry["entryHash"] = self._hash(entry)
            self.entries.append(entry)
        return entry

    def hydrate(self, entries: list[dict[str, Any]], persisted_max_sequence: int = 0) -> None:
        """Load the persisted ledger (ordered by sequence) and continue numbering above it."""
        with self._lock:
            self.entries.extend(entries)
            known = max((entry.get("sequence") or 0 for entry in self.entries), default=0)
            self._last_sequence = max(self._last_sequence, known, persisted_max_sequence or 0)

    def reconcile_for_persistence(self, persisted: dict[int, Any], skip=lambda entry: False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return the entries to write to a ledger that already holds `persisted`
        (sequence -> entryHash of rows the snapshot keeps).

        - An entry identical (same sequence and entryHash) to a kept row, or to an
          earlier in-memory entry, is written once: persistence is idempotent.
        - An entry whose sequence is held by a *different* record was allocated
          from stale numbering.  It is never dropped: it is re-appended at the
          head of the ledger under a fresh sequence above everything persisted,
          re-chained to the current tail, and keeps `resequencedFrom`.
        Returns (entries_to_write, resequenced_entries).
        """
        with self._lock:
            self._last_sequence = max([self._last_sequence, *persisted.keys()])
            to_write, conflicts, seen, keep = [], [], {}, []
            conflict_hashes = set()
            for entry in self.entries:
                sequence, entry_hash = entry.get("sequence"), entry.get("entryHash")
                if entry_hash in conflict_hashes:
                    continue  # a second copy of a record already being re-appended
                if sequence in seen:
                    if seen[sequence] == entry_hash:
                        continue  # the same record twice in memory: keep one copy
                    conflicts.append(entry); conflict_hashes.add(entry_hash)
                    continue
                if not skip(entry) and sequence in persisted:
                    if persisted[sequence] != entry_hash:
                        conflicts.append(entry); conflict_hashes.add(entry_hash)
                        continue
                else:
                    if not skip(entry):
                        to_write.append(entry)
                seen[sequence] = entry_hash
                keep.append(entry)
            self.entries[:] = keep
            for entry in conflicts:
                entry["resequencedFrom"] = entry["sequence"]
                entry["sequence"] = self._next_sequence()
                entry["previousHash"] = self.entries[-1]["entryHash"] if self.entries else "GENESIS"
                entry["entryHash"] = self._hash(entry)
                self.entries.append(entry)
                to_write.append(entry)
            return to_write, conflicts

    def verify(self) -> bool:
        previous = "GENESIS"
        for entry in self.entries:
            if entry["previousHash"] != previous or self._hash(entry) != entry["entryHash"]:
                return False
            previous = entry["entryHash"]
        return True

    def handle_event(self, event: dict[str, Any]) -> None:
        """Record workflow status events without storing their sensitive payload."""
        event_id = event.get("eventId")
        if event_id and event_id in self._processed_event_ids:
            return
        payload = event.get("payload", {})
        self.append(
            payload.get("actor") or event.get("actor") or "SYSTEM",
            "APPLICATION",
            "Workflow state transition",
            event.get("source", "workflow_engine"),
            payload.get("status", event.get("type", "EVENT")),
            payload.get("consentId"),
            {"eventId": event_id, "appId": event.get("applicationId"), "status": payload.get("status")},
            event.get("correlationId"),
        )
        if event_id:
            self._processed_event_ids.add(event_id)

    def reset(self) -> None:
        with self._lock:
            self.entries.clear()
            self._processed_event_ids.clear()
            self._last_sequence = 0


audit_bus = AuditBus()

from app.core.event_bus import event_bus
event_bus.subscribe("APPLICATION_STATUS_CHANGED", audit_bus.handle_event)
