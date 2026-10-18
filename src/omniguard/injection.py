"""Injection sanitizer (Graph1 Node 1). Deterministic, no LLM.

- Preserves the raw memo (evidence integrity, never deleted).
- Regex-scans attacker-controlled fields (memo, counterparty_name).
- XML-sandboxes values for LLM consumption.
- Flags quarantine -> caller forces CONFLICT_HUMAN_REVIEW.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Dict

INJECTION_PATTERNS = [
    r"(?i)ignore\s+(previous|all|above)",
    r"(?i)system\s*prompt",
    r"(?i)you\s+are\s+now",
    r"(?i)disregard",
    r"(?i)override",
    r"(?i)new\s+instructions?",
    r"(?i)<\s*/?\s*untrusted_transaction_memo\s*>",
]

ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff]")


def _normalize_for_scan(text: str) -> str:
    """Normalize Unicode homoglyphs and strip zero-width characters before regex check."""
    normalized = unicodedata.normalize("NFKC", text or "")
    return ZERO_WIDTH_RE.sub("", normalized)


def scan_text(value: str | None) -> bool:
    if not value:
        return False
    scan_val = _normalize_for_scan(str(value))
    return any(re.search(p, scan_val) for p in INJECTION_PATTERNS)


def sandbox(raw_memo: str | None, tag: str = "untrusted_transaction_memo") -> str:
    """Escape XML/HTML delimiters so untrusted input can never break out of the sandbox tag."""
    safe_text = html.escape(raw_memo or "", quote=True)
    return f"<{tag}>{safe_text}</{tag}>"


def scan_transaction(tx: Dict[str, Any]) -> Dict[str, Any]:
    """Scan all untrusted transaction text fields (memo + counterparty_name) without mutating raw values."""
    flagged_fields = []
    for field in ("memo", "counterparty_name"):
        raw_val = str(tx.get(field) or "")
        scan_val = _normalize_for_scan(raw_val)
        if any(re.search(p, scan_val) for p in INJECTION_PATTERNS):
            flagged_fields.append(field)

    return {
        "quarantined": len(flagged_fields) > 0,
        "flagged_fields": flagged_fields,
    }