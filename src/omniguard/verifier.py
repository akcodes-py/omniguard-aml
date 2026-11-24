"""Deterministic verification + adjudication (Graph1 Node 5). Code only, no LLM.

Checks:
- citations_valid: every cited tx_id exists in the fetched window; every
  cited policy_id@version exists and is current (effective_to IS NULL);
  every numeric claim (amounts) matches SQL-computed values within 0.01.
- math_valid: LLM-stated totals equal precomputed features.
- disposition: PRD Sec 5 boolean logic + injection quarantine override.
  Never auto-closes: RECOMMEND_* are recommendations; the human gate always fires.
"""
from __future__ import annotations

from .config import settings


def verify_citations(investigator: dict, tx_ids: set[str], policies: list[dict], features: dict) -> dict:
    cited_tx = investigator.get("cited_tx_ids") or []
    cited_pol = investigator.get("cited_policy_ids") or []
    current = {(p["policy_id"], p["version"]) for p in policies if p.get("effective_to") is None}
    if tx_ids:
        tx_ok = bool(cited_tx) and all(c in tx_ids for c in cited_tx)
    else:
        tx_ok = True
    # An empty citation list must NOT be vacuously valid: an output with no
    # grounded policy citation is misinformation risk (LLM07:2026).
    pol_ok = bool(cited_pol) and all(
        tuple(c) in current if isinstance(c, (list, tuple)) else False for c in cited_pol
    )
    # numeric claims: {"total_in": x, ...} optionally supplied by the LLM
    math_ok = True
    for k, v in (investigator.get("numeric_claims") or {}).items():
        if k in features:
            try:
                if abs(float(v) - float(features[k])) > 0.01:
                    math_ok = False
            except (TypeError, ValueError):
                math_ok = False
    valid = bool(tx_ok and pol_ok and math_ok)
    return {"tx_ok": tx_ok, "pol_ok": pol_ok, "math_ok": math_ok, "citations_valid": valid}


# KYC fields an LLM challenger may cite to support an exoneration. An
# ungrounded boolean from a hostile prompt is worthless; the cited field must
# exist in the fetched account row (OWASP LLM03:2026 / ASI01:2026).
VERIFIED_KYC_FIELDS: frozenset[str] = frozenset({
    "account_purpose", "occupation", "occupation_category",
    "parent_entity_id", "high_risk_jurisdiction", "account_type",
})


def verify_exoneration(challenger: dict, account: dict) -> bool:
    """Return True only when the challenger's exoneration is DB-grounded.

    A prompt injection can trivially set ``has_verified_kyc_exoneration=true``.
    This guard ignores that claim unless at least one cited field is a known
    KYC column with a non-empty value in the deterministic account state.
    """
    if not bool(challenger.get("has_verified_kyc_exoneration")):
        return False
    fields = challenger.get("cited_data_fields") or []
    if not isinstance(fields, (list, tuple)):
        return False
    return any(
        isinstance(field, str) and field in VERIFIED_KYC_FIELDS
        and bool(str(account.get(field) or "").strip())
        for field in fields
    )


def hitl_required(disposition: str) -> bool:
    """Every adjudication result is a recommendation; a human always decides."""
    return disposition.startswith("RECOMMEND_") or disposition == "CONFLICT_HUMAN_REVIEW"


def adjudicate(composite: float, has_exoneration: bool, citations_valid: bool, quarantined: bool) -> str:
    if quarantined or not citations_valid:
        return "CONFLICT_HUMAN_REVIEW"
    if composite > settings.ESCALATE_THRESHOLD and not has_exoneration:
        return "RECOMMEND_ESCALATE"
    if composite < settings.CLOSE_THRESHOLD and has_exoneration:
        return "RECOMMEND_CLOSE"
    return "CONFLICT_HUMAN_REVIEW"
