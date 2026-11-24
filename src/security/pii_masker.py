"""Deterministic PII masking layer (OWASP LLM02:2026).

Every alert payload is passed through :func:`mask_payload` *before* it is
rendered into an outbound Investigator/Challenger prompt. The masker is pure
Python: no LLM, no randomness, no I/O.

Design
------
* **Deterministic tokens.** Each distinct raw value receives
  ``[CATEGORY_001]``, ``[CATEGORY_002]`` ... in a stable traversal order
  (dict keys sorted, lists in order). The same payload always yields the
  same tokens; repeated values inside one payload share a token.
* **Two interception paths.**
  1. Field-name masking for known sensitive keys (customer name, account
     number, email, phone, SSN/PAN, ...).
  2. Content regex scanning for PII embedded in free text (memos, prompts,
     narratives), plus optional ``known_names`` harvested from the alert's
     KYC/counterparty records.
* **Citation safety.** Transaction IDs and policy IDs are deliberately
  *not* masked — the verifier needs them to check grounded citations.
* **No raw values are logged.** Only category counts and token names are
  exposed in :class:`MaskResult`; the raw-to-token map is internal.

The calling pipeline logs ``MaskResult.counts`` via ``security.audit_logger``
so masking is observable without re-disclosing the data it protected.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Field-level rules: key (case-insensitive) -> token category
# ---------------------------------------------------------------------------
SENSITIVE_KEYS: dict[str, str] = {
    # people
    "customer_name": "PERSON", "full_name": "PERSON", "name": "PERSON",
    "counterparty_name": "PERSON", "beneficiary_name": "PERSON",
    "sender_name": "PERSON", "recipient_name": "PERSON",
    # accounts
    "account_id": "ACCT", "account_number": "ACCT", "acct_id": "ACCT",
    "acct_number": "ACCT", "customer_id": "ACCT", "iban": "ACCT",
    "source_account": "ACCT", "destination_account": "ACCT",
    "src_account": "ACCT", "dst_account": "ACCT",
    # contact details / government IDs
    "email": "EMAIL", "email_address": "EMAIL", "e_mail": "EMAIL",
    "phone": "PHONE", "phone_number": "PHONE", "mobile": "PHONE",
    "mobile_number": "PHONE", "telephone": "PHONE",
    "ssn": "SSN", "social_security_number": "SSN", "national_id": "SSN",
    "tax_id": "SSN", "passport": "SSN",
    "pan": "PAN", "card_number": "PAN", "credit_card": "PAN",
    "debit_card": "PAN", "card_no": "PAN",
}

# Keys whose values must survive verbatim: deterministic adjudication depends
# on them (citation checks, numeric feature checks, policy version checks).
PRESERVED_KEYS: frozenset[str] = frozenset({
    "tx_ids", "cited_tx_ids", "policy_ids", "cited_policy_ids", "cited_data_fields",
    "facts", "features", "graph_features", "ml_scores", "numeric_claims",
    "shap_explanation", "policy_version", "version", "version_hash", "policy_id",
    "run_id", "thread_id", "alert_id", "case_id",
})

# ---------------------------------------------------------------------------
# Content-level rules. Order matters: emails first, then long IDs, then
# phones, then labelled account numbers.
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PAN_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)"
)
LABELLED_ACCT_RE = re.compile(
    r"\b(?:account|acct|iban|account\s*number)\s*[:#]?\s*([A-Z][A-Z0-9-]{3,}|\d{6,})\b", re.I
)
IDENTIFIER_ACCT_RE = re.compile(r"\b(?:ACCT|ACC)[-_ ]?[A-Z0-9]{3,}\b", re.I)
# Conservative proper-name heuristic for names not present in the KYC registry:
# two or more title-cased words. Common policy/sentence phrases are excluded.
NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+)\b")
_NAME_STOPWORDS = frozenset({
    "ignore", "previous", "instructions", "system", "prompt", "please", "return",
    "the", "this", "that", "you", "are", "now", "risk", "rapid", "pass", "through",
    "structuring", "layering", "general", "human", "policy", "shell", "high",
    "correspondent", "round", "payroll", "treasury", "merchant", "shared", "velocity",
    "candidate", "auto", "close", "alert", "wire", "email", "contact", "from", "contact",
})

TOKEN_RE = re.compile(r"\[[A-Z]+_\d{3,}\]")

_CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", EMAIL_RE),
    ("SSN", SSN_RE),
    ("PAN", PAN_RE),
    ("PHONE", PHONE_RE),
    ("ACCT", LABELLED_ACCT_RE),
    ("ACCT", IDENTIFIER_ACCT_RE),
)


@dataclass(frozen=True)
class MaskResult:
    """Masked payload plus *metadata only* (never raw values)."""

    payload: Any
    counts: dict[str, int] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)  # token -> category
    total: int = 0

    def __add__(self, other: "MaskResult") -> "MaskResult":
        """Merge two results (used for the parallel investigator/challenger payloads)."""
        counts = dict(Counter(self.counts) + Counter(other.counts))
        tokens = {**self.tokens, **other.tokens}
        return MaskResult(
            payload=[self.payload, other.payload],
            counts=counts, tokens=tokens, total=sum(counts.values()),
        )


class _Masker:
    """Stateful per-payload masker. Instances are *not* shared between calls."""

    def __init__(self, known_names: Iterable[str] = ()) -> None:
        self._seen: dict[tuple[str, str], str] = {}
        self._counters: Counter[str] = Counter()
        self._counts: Counter[str] = Counter()
        self._tokens: dict[str, str] = {}
        # Longest first so a full name wins over a partial match.
        self._names = sorted(
            {n.strip() for n in known_names if isinstance(n, str) and len(n.strip()) >= 3},
            key=len, reverse=True,
        )

    def token(self, category: str, raw: str) -> str:
        key = (category, raw)
        if key not in self._seen:
            self._counters[category] += 1
            value = f"[{category}_{self._counters[category]:03d}]"
            self._seen[key] = value
            self._tokens[value] = category
        token = self._seen[key]
        self._counts[category] += 1
        return token

    def text(self, value: str) -> str:
        # Park tokens from an upstream masking pass so they are neither
        # renumbered nor double-counted, while still scanning the *rest* of
        # the same string for additional PII.
        parked: dict[str, str] = {}

        def _park(match: re.Match[str]) -> str:
            token = match.group(0)
            slot = f"\x00MASKED{len(parked)}\x00"
            parked[slot] = token
            return slot

        out = TOKEN_RE.sub(_park, value)
        for name in self._names:
            if name.lower() in out.lower():
                out = re.sub(re.escape(name), self.token("PERSON", name), out, flags=re.I)

        def _mask_name(match: re.Match[str]) -> str:
            candidate = match.group(1)
            if any(w.lower() in _NAME_STOPWORDS for w in candidate.split()):
                return candidate
            return self.token("PERSON", candidate)

        out = NAME_RE.sub(_mask_name, out)
        for category, pattern in _CONTENT_RULES:
            if category == "ACCT" and pattern is LABELLED_ACCT_RE:
                out = pattern.sub(
                    lambda m: m.group(0).replace(m.group(1), self.token("ACCT", m.group(1))), out
                )
            else:
                out = pattern.sub(lambda m: self.token(category, m.group(0)), out)
        for slot, token in parked.items():
            out = out.replace(slot, token)
        return out

    def walk(self, node: Any, key: str = "") -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for k in sorted(node, key=str):  # stable traversal
                v = node[k]
                if str(k).lower() in PRESERVED_KEYS:
                    result[k] = v
                elif str(k).lower() in SENSITIVE_KEYS and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                    result[k] = self.token(SENSITIVE_KEYS[str(k).lower()], str(v))
                else:
                    result[k] = self.walk(v, k)
            return result
        if isinstance(node, list):
            return [self.walk(v, key) for v in node]
        if isinstance(node, tuple):
            return tuple(self.walk(v, key) for v in node)
        if isinstance(node, str):
            return self.text(node)
        return node  # numbers / bools / None pass through untouched

    def result(self, payload: Any) -> MaskResult:
        masked = self.walk(payload)
        return MaskResult(
            payload=masked, counts=dict(self._counts),
            tokens=dict(self._tokens), total=sum(self._counts.values()),
        )


def mask_payload(payload: Any, known_names: Iterable[str] = ()) -> MaskResult:
    """Return a deep-copied payload with all detected PII replaced by stable tokens.

    The input is never mutated. Calling twice with the same input (and names)
    yields byte-identical ``payload`` and ``counts``.
    """
    return _Masker(known_names).result(payload)


def contains_pii(value: Any) -> bool:
    """True when free text still carries an unmasked PII pattern (test/audit helper)."""
    if isinstance(value, str):
        if TOKEN_RE.search(value):
            value = TOKEN_RE.sub("", value)
        return any(p.search(value) for _, p in _CONTENT_RULES)
    if isinstance(value, dict):
        return any(
            (str(k).lower() in SENSITIVE_KEYS
             and bool(str(v).strip()) and not TOKEN_RE.fullmatch(str(v)))
            or contains_pii(v)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_pii(v) for v in value)
    return False
