"""Structured security event audit log (OWASP A09:2025).

Every control action is append-only and carries the same minimal schema:

    timestamp, event_id, case_id, owasp_category, action_taken, details

What is logged (and what is deliberately *not* logged):
* quarantined prompt injections (transaction memos and RAG chunks),
* deterministic PII mask counts (category -> count, never raw values),
* citation/grounding failures,
* HITL escalations and analyst decisions.

Sinks
-----
1. **JSONL** (always): path from ``settings.SECURITY_LOG_PATH``. One JSON
   object per line, flushed and fsync'd — safe as an incident-evidence trail.
2. **PostgreSQL** (opt-in via ``settings.SECURITY_DB_SINK=true``): INSERT into
   ``audit.security_events`` using the project's dialect-aware DB helper.
   A DB failure is warned about but never breaks the investigation path;
   the JSONL copy remains authoritative for that run.

Raw transaction text, customer names, account numbers and other PII are never
passed to either sink — callers provide counts and opaque case/run IDs only.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()

# Canonical tags used by the security tests and the model card.
LLM01 = "LLM01:2026"          # prompt injection (incl. indirect/RAG)
LLM02 = "LLM02:2026"          # sensitive information disclosure
LLM03 = "LLM03:2026"          # excessive agency
LLM07 = "LLM07:2026"          # misinformation / ungrounded output
LLM09 = "LLM09:2026"          # vector & embedding weaknesses
ASI01 = "ASI01:2026"          # agent goal hijack
ASI09 = "ASI09:2026"          # human-agent trust exploitation
A09 = "A09:2025"              # logging & alerting failures


@dataclass(frozen=True)
class SecurityEvent:
    """One immutable audit record. ``details`` must contain metadata only."""

    case_id: str
    owasp_category: str
    action_taken: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        # Stable key order makes JSONL diffs and evidence hashing reproducible.
        return {
            "timestamp": record["timestamp"],
            "event_id": record["event_id"],
            "case_id": record["case_id"],
            "owasp_category": record["owasp_category"],
            "action_taken": record["action_taken"],
            "details": record["details"],
        }


def _log_path() -> Path:
    from omniguard.config import settings

    path = Path(settings.SECURITY_LOG_PATH)
    return path if path.is_absolute() else Path.cwd() / path


def _write_jsonl(record: dict[str, Any]) -> None:
    path = _log_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            import os

            os.fsync(fh.fileno())


def _write_db(record: dict[str, Any]) -> None:
    """Fail-soft secondary sink; JSONL remains authoritative on any error."""
    from omniguard.config import settings
    from omniguard.db import connect, dumps, run, t

    try:
        con = connect()
    except Exception as e:  # noqa: BLE001 - monitoring outage must not block AML triage
        _log.warning("security audit DB sink unavailable (%s); JSONL retained", e)
        return
    try:
        cur = con.cursor()
        run(cur,
            f"INSERT INTO {t('security_events')} "  # nosec B608 - table name from fixed t() whitelist, all values bound
            "(event_id, timestamp, case_id, owasp_category, action_taken, details) "
            "VALUES (?,?,?,?,?,?)",
            (record["event_id"], record["timestamp"], record["case_id"],
             record["owasp_category"], record["action_taken"],
             dumps(record["details"])))
        if hasattr(con, "commit"):
            con.commit()
    except Exception as e:  # noqa: BLE001 - monitoring outage must not block AML triage
        _log.warning("security audit DB sink unavailable (%s); JSONL retained", e)
    finally:
        con.close()


def log_security_event(event: SecurityEvent | None = None, **kwargs: Any) -> dict[str, Any]:
    """Append a security event. Accepts a ``SecurityEvent`` or keyword fields.

    Returns the exact record written, which is handy for assertions and for
    correlating an event ID with the investigation run.
    """
    if event is None:
        event = SecurityEvent(**kwargs)
    record = event.to_dict()
    _write_jsonl(record)

    from omniguard.config import settings

    if settings.SECURITY_DB_SINK:
        _write_db(record)
    return record


def read_security_events(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read the JSONL trail (operations / tests). Missing file => empty list."""
    target = Path(path) if path else _log_path()
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def events_for_case(case_id: str, path: str | Path | None = None) -> Iterable[dict[str, Any]]:
    return [e for e in read_security_events(path) if e.get("case_id") == case_id]
