"""Injection sanitizer (Graph1 Node 1). Deterministic, no LLM.

- Preserves the raw memo (evidence integrity, never deleted).
- Regex-scans attacker-controlled fields (memo, counterparty_name).
- XML-sandboxes values for LLM consumption.
- Flags quarantine -> caller forces CONFLICT_HUMAN_REVIEW.
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"(?i)ignore\s+(previous|all|above)",
    r"(?i)system\s*prompt",
    r"(?i)you\s+are\s+now",
    r"(?i)disregard",
    r"(?i)override",
    r"(?i)new\s+instructions?",
]
_COMPILED = [re.compile(p) for p in INJECTION_PATTERNS]

UNTRUSTED_FIELDS = ("memo", "counterparty_name")


def scan_text(value: str | None) -> bool:
    if not value:
        return False
    return any(rx.search(value) for rx in _COMPILED)


def sandbox(tag: str, value: str | None) -> str:
    return f"<untrusted_{tag}>{value or ''}</untrusted_{tag}>"


def scan_transaction(tx: dict) -> dict:
    """Return {flagged_fields, quarantined, sanitized} — raw values preserved in tx."""
    flagged = [f for f in UNTRUSTED_FIELDS if scan_text(tx.get(f))]
    sanitized = {f: sandbox("transaction_memo" if f == "memo" else f, tx.get(f)) for f in UNTRUSTED_FIELDS}
    return {"flagged_fields": flagged, "quarantined": bool(flagged), "sanitized": sanitized}
