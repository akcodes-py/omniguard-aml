"""Graph1 Investigation pipeline (PRD Sec 5): Real LangGraph StateGraph with 8 nodes.

Architecture:
  1 fetch_and_sanitize → 2 compute_features → 3 ml_risk_scoring →
  4 retrieve_policies → 5 dual_llm (investigator ∥ challenger) →
  6 verify_and_adjudicate → 7 write_audit_record →
  [interrupt_before] → 8 human_gate

Checkpointer: MemorySaver (local default) or AsyncPostgresSaver (Postgres).
Interrupt: Graph execution pauses before human_gate via interrupt_before,
  saving full state to the checkpointer for crash recovery. The analyst's
  decision is handled by review() which writes to audit.human_decisions.

run_investigation(alert_id) invokes the graph through nodes 1-7, pausing
  at the interrupt point. Returns AWAITING_HUMAN_REVIEW state.
review(alert_id, run_id, analyst_id, decision, rationale) performs
  staleness check and writes the human decision to the audit trail.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import features as feat
from . import graph_features as gf
from . import injection as inj
from . import llm
from . import ml
from . import policy_retrieval as pr
from . import verifier as ver
from .config import settings
from .db import connect, dumps, fetchall, fetchone, loads, run, t
from .prompts import prompt_version_hash
from security import audit_logger as audit
from security import pii_masker as pii


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class InvestigationState(TypedDict, total=False):
    """Typed state flowing through the 8-node investigation StateGraph."""
    # Input
    alert_id: str
    thread_id: str
    # Node 1: fetch_and_sanitize
    alert: dict[str, Any]
    account: dict[str, Any]
    txs: list[dict[str, Any]]
    high_risk_accounts: list[str]       # list (not set) for JSON checkpointing
    tx_ids: list[str]
    injection_scan: dict[str, Any]
    quarantined: bool
    sanitized_memos: list[str]
    # Security controls: PII masking (LLM02) + RAG chunk quarantine (LLM01/09)
    pii_mask_counts: dict[str, int]
    pii_tokens: dict[str, str]              # token -> category, no raw values
    policy_quarantined: bool
    policy_scan: dict[str, Any]
    # Node 2: compute_features
    features: dict[str, Any]
    graph_features: dict[str, Any]
    # Node 3: ml_risk_scoring
    ml_scores: dict[str, Any]
    shap_explanation: list[dict[str, Any]]
    # Node 4: retrieve_policies
    policies: list[dict[str, Any]]
    # Node 5: dual_llm
    investigator_output: dict[str, Any]
    investigator_tc: dict[str, Any]
    challenger_output: dict[str, Any]
    challenger_tc: dict[str, Any]
    # Node 6: verify_and_adjudicate
    verifier_result: dict[str, Any]
    disposition: str
    # Node 7: write_audit_record
    run_id: str
    token_cost: dict[str, Any]
    state: str                          # AWAITING_HUMAN_REVIEW | FINALIZED


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _rows(cur, sql, args=()):
    return fetchall(cur, sql, args)


def _row(cur, sql, args=()):
    return fetchone(cur, sql, args)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def fetch_alert(alert_id: str) -> dict:
    con = connect()
    try:
        cur = con.cursor()
        alert = _row(cur, f"SELECT * FROM {t('alerts')} WHERE alert_id=?", (alert_id,))  # nosec B608 - table name from fixed t() whitelist, all values bound
        if not alert:
            raise KeyError(f"alert not found: {alert_id}")
        acct = _row(cur, f"SELECT * FROM {t('accounts')} WHERE account_id=?", (alert["account_id"],))  # nosec B608 - table name from fixed t() whitelist, all values bound
        txs = _rows(cur, f"SELECT * FROM {t('transactions')} WHERE src_account=? OR dst_account=? ORDER BY ts",  # nosec B608 - table name from fixed t() whitelist, all values bound
                    (alert["account_id"], alert["account_id"]))
        hrs = _rows(cur, f"SELECT account_id FROM {t('accounts')} WHERE high_risk_jurisdiction")  # nosec B608 - table name from fixed t() whitelist, all values bound
        hr_set = {r["account_id"] for r in hrs}
        return {"alert": alert, "account": acct or {}, "txs": txs, "high_risk": hr_set}
    finally:
        con.close()


def _typology_tags(features: dict) -> list[str]:
    tags = []
    if features.get("pass_through_ratio", 0) > 0.8:
        tags.append("rapid_pass_through")
    if features.get("structuring_flags", 0) > 0:
        tags.append("structuring")
    if features.get("night_ratio", 0) > 0.5:
        tags.append("layering")
    tags.append("general")
    return tags


# ---------------------------------------------------------------------------
# Node functions (each takes InvestigationState, returns partial update)
# ---------------------------------------------------------------------------

async def node_fetch_and_sanitize(state: InvestigationState) -> dict:
    """Node 1: Fetch alert + transactions + KYC from DB; scan for prompt injection."""
    bundle = fetch_alert(state["alert_id"])
    alert, acct, txs = bundle["alert"], bundle["account"], bundle["txs"]
    tx_ids = [r["tx_id"] for r in txs]

    scans = [inj.scan_transaction(tx) for tx in txs]
    quarantined = any(s["quarantined"] for s in scans)
    injection_scan = {
        "flagged_fields": [s["flagged_fields"] for s in scans if s["flagged_fields"]],
        "quarantined": quarantined,
    }
    memos = [inj.sandbox(tx.get("memo"), tag="transaction_memo") for tx in txs]

    if quarantined:
        audit.log_security_event(
            case_id=state["alert_id"], owasp_category=audit.LLM01,
            action_taken="QUARANTINED_TRANSACTION_INJECTION",
            details={"flagged_fields": injection_scan["flagged_fields"],
                     "n_flagged_tx": sum(1 for s in scans if s["quarantined"])},
        )

    return {
        "alert": alert, "account": acct, "txs": txs,
        "high_risk_accounts": list(bundle["high_risk"]),
        "tx_ids": tx_ids, "injection_scan": injection_scan,
        "quarantined": quarantined, "sanitized_memos": memos,
    }


async def node_compute_features(state: InvestigationState) -> dict:
    """Node 2: Deterministic features (12) + NetworkX graph analytics (7)."""
    hr_set = set(state.get("high_risk_accounts", []))
    acct_id = state["alert"]["account_id"]
    f = feat.compute_features(state["txs"], acct_id, hr_set)
    g = gf.compute_graph_features(state["txs"], acct_id, hr_set)
    return {"features": f, "graph_features": g}


async def node_ml_risk_scoring(state: InvestigationState) -> dict:
    """Node 3: LightGBM supervised + IsolationForest anomaly scoring + SHAP."""
    f, g = state["features"], state["graph_features"]
    vec = ml.to_vector(f, g)
    try:
        scores = ml.score(vec)
        shap_exp = ml.explain(vec)
    except FileNotFoundError:
        comp = min(0.95, 0.15 + 0.6 * f.get("pass_through_ratio", 0)
                   + 0.05 * f.get("structuring_flags", 0))
        scores = {"supervised": round(comp, 4), "anomaly": 0.5,
                  "composite": round(comp, 4), "fallback": True}
        shap_exp = [{"feature": "pass_through_ratio",
                     "value": f.get("pass_through_ratio", 0)}]
    return {"ml_scores": scores, "shap_explanation": shap_exp}


async def node_retrieve_policies(state: InvestigationState) -> dict:
    """Node 4: Retrieve policies via pgvector / pseudo-embed and quarantine
    poisoned chunks before they can reach the LLM (LLM01:2026 / LLM09:2026)."""
    retrieved = pr.retrieve(
        _typology_tags(state["features"]),
        state["alert"].get("trigger_reason", ""),
    )
    scans = [inj.scan_policy_chunk(p) for p in retrieved]
    flagged = [
        {"policy_id": p["policy_id"], "flagged_fields": s["flagged_fields"]}
        for p, s in zip(retrieved, scans) if s["quarantined"]
    ]
    policy_quarantined = bool(flagged)
    # Infected chunks are never passed to the investigator; metadata only is
    # retained in state so the analyst can see which policy version was hit.
    policies = [p for p, s in zip(retrieved, scans) if not s["quarantined"]]
    if policy_quarantined:
        audit.log_security_event(
            case_id=state["alert_id"], owasp_category=f"{audit.LLM01}/{audit.LLM09}",
            action_taken="QUARANTINED_RAG_CHUNK",
            details={"flagged": flagged, "n_dropped": len(flagged)},
        )
    return {
        "policies": policies,
        "policy_quarantined": policy_quarantined,
        "policy_scan": {"quarantined": policy_quarantined, "flagged": flagged},
    }


async def node_dual_llm(state: InvestigationState) -> dict:
    """Node 5: Mask every alert payload, then parallel investigator + challenger calls.

    Masking happens here (the LangGraph boundary) and again at ``llm.call_json``
    (the provider boundary) so no caller can bypass it. Only masked payloads are
    rendered into outbound prompts; ``tx_ids``/``policy_ids`` are preserved for
    citation verification.
    """
    inv_payload = {
        "facts": state["features"], "tx_ids": state["tx_ids"],
        "policy_ids": [[p["policy_id"], p["version"]] for p in state["policies"]],
        "policies": [p["title"] for p in state["policies"]],
        "memos": state["sanitized_memos"],
    }
    chal_payload = {"facts": state["features"], "kyc": state["account"]}
    known_names = [state["account"].get("customer_name", "")]
    known_names.extend(tx.get("counterparty_name", "") for tx in state["txs"])

    masked_inv = pii.mask_payload(inv_payload, known_names=known_names)
    masked_chal = pii.mask_payload(chal_payload, known_names=known_names)
    counts = dict(Counter(masked_inv.counts) + Counter(masked_chal.counts))
    audit.log_security_event(
        case_id=state["alert_id"], owasp_category=audit.LLM02,
        action_taken="PII_MASK_APPLIED",
        details={"counts": counts, "total": sum(counts.values()),
                 "targets": ["investigator", "challenger"]},
    )

    (inv_out, inv_tc), (chal_out, chal_tc) = await asyncio.gather(
        asyncio.to_thread(llm.call_json, "investigator", masked_inv.payload),
        asyncio.to_thread(llm.call_json, "challenger", masked_chal.payload),
    )
    return {
        "investigator_output": inv_out, "investigator_tc": inv_tc,
        "challenger_output": chal_out, "challenger_tc": chal_tc,
        "pii_mask_counts": counts,
        "pii_tokens": {**masked_inv.tokens, **masked_chal.tokens},
    }


async def node_verify_and_adjudicate(state: InvestigationState) -> dict:
    """Node 6: Citation verification + numeric match + boolean adjudication."""
    vr = ver.verify_citations(
        state["investigator_output"], set(state["tx_ids"]),
        state["policies"], state["features"],
    )
    # An injected prompt can flip a boolean; it cannot fabricate a KYC field.
    has_ex = ver.verify_exoneration(state["challenger_output"], state["account"])
    quarantined = bool(state.get("quarantined")) or bool(state.get("policy_quarantined"))
    disp = ver.adjudicate(
        state["ml_scores"]["composite"], has_ex,
        vr["citations_valid"], quarantined,
    )
    if not vr["citations_valid"]:
        audit.log_security_event(
            case_id=state["alert_id"], owasp_category=audit.LLM07,
            action_taken="UNGROUNDED_OUTPUT_FLAGGED",
            details={"tx_ok": vr["tx_ok"], "pol_ok": vr["pol_ok"],
                     "math_ok": vr["math_ok"], "disposition": disp},
        )
    if ver.hitl_required(disp):
        audit.log_security_event(
            case_id=state["alert_id"], owasp_category=f"{audit.LLM03}/{audit.ASI01}",
            action_taken="HITL_ESCALATION",
            details={"disposition": disp, "quarantined": quarantined,
                     "citations_valid": vr["citations_valid"]},
        )
    return {
        "verifier_result": {**vr, "disposition": disp, "exoneration_grounded": has_ex},
        "disposition": disp,
    }


async def node_write_audit_record(state: InvestigationState) -> dict:
    """Node 7: Persist immutable audit record to investigation_runs."""
    run_id = uuid.uuid4().hex
    thread_id = state.get("thread_id") or f"investigate-{state['alert_id']}-{run_id[:8]}"
    token_cost = {
        "investigator": state["investigator_tc"],
        "challenger": state["challenger_tc"],
        "total": state["investigator_tc"].get("total", 0)
               + state["challenger_tc"].get("total", 0),
    }
    tx_ids = state.get("tx_ids", [])
    con = connect()
    try:
        cur = con.cursor()
        cols = ("run_id, alert_id, thread_id, tx_watermark, features, graph_features,"
                " ml_scores, shap_explanation, injection_scan, retrieved_policies,"
                " investigator_output, challenger_output, verifier_result, disposition,"
                " prompt_version_hash, model_id, token_cost")
        run(cur,
              f"INSERT INTO {t('investigation_runs')} ({cols}) VALUES ("  # nosec B608 - table name from fixed t() whitelist, all values bound
              + ",".join(["?"] * 17) + ")",
              (run_id, state["alert_id"], thread_id,
               tx_ids[-1] if tx_ids else "",
               dumps(state["features"]), dumps(state["graph_features"]),
               dumps(state["ml_scores"]), dumps(state["shap_explanation"]),
               dumps(state["injection_scan"]),
               dumps([{"policy_id": p["policy_id"], "version": p["version"],
                       "version_hash": p["version_hash"]} for p in state["policies"]]),
               dumps(state["investigator_output"]), dumps(state["challenger_output"]),
               dumps(state["verifier_result"]), state["disposition"],
               prompt_version_hash(),
               state["investigator_tc"].get("model_id", settings.BEDROCK_MODEL_ID),
               dumps(token_cost)))
        if hasattr(con, "commit"):
            con.commit()
    finally:
        con.close()
    return {
        "run_id": run_id, "thread_id": thread_id,
        "token_cost": token_cost, "state": "AWAITING_HUMAN_REVIEW",
    }


async def node_human_gate(state: InvestigationState) -> dict:
    """Node 8: Human review gate. Graph pauses HERE via interrupt_before.

    In the standard API flow, the analyst's decision is handled by review()
    outside the graph. This node runs only if the graph is explicitly
    resumed after the analyst acts (e.g. via graph.ainvoke(None, config))."""
    return {"state": "FINALIZED"}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_langgraph(checkpointer=None):
    """Build the real 8-node investigation StateGraph.

    Args:
        checkpointer: LangGraph checkpointer instance. Defaults to MemorySaver.
            For Postgres persistence, pass AsyncPostgresSaver after calling
            await checkpointer.setup().

    Returns:
        Compiled LangGraph with interrupt_before on human_gate.
    """
    builder = StateGraph(InvestigationState)

    # Register all 8 pipeline nodes
    builder.add_node("fetch_and_sanitize", node_fetch_and_sanitize)
    builder.add_node("compute_features", node_compute_features)
    builder.add_node("ml_risk_scoring", node_ml_risk_scoring)
    builder.add_node("retrieve_policies", node_retrieve_policies)
    builder.add_node("dual_llm", node_dual_llm)
    builder.add_node("verify_and_adjudicate", node_verify_and_adjudicate)
    builder.add_node("write_audit_record", node_write_audit_record)
    builder.add_node("human_gate", node_human_gate)

    # Linear pipeline: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → END
    builder.add_edge(START, "fetch_and_sanitize")
    builder.add_edge("fetch_and_sanitize", "compute_features")
    builder.add_edge("compute_features", "ml_risk_scoring")
    builder.add_edge("ml_risk_scoring", "retrieve_policies")
    builder.add_edge("retrieve_policies", "dual_llm")
    builder.add_edge("dual_llm", "verify_and_adjudicate")
    builder.add_edge("verify_and_adjudicate", "write_audit_record")
    builder.add_edge("write_audit_record", "human_gate")
    builder.add_edge("human_gate", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_gate"],
    )


# Singleton graph instance (lazy init, MemorySaver default)
_graph_instance = None


def _get_graph():
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_langgraph()
    return _graph_instance


# ---------------------------------------------------------------------------
# Public API (backward-compatible signatures)
# ---------------------------------------------------------------------------

async def run_investigation(alert_id: str, thread_id: str | None = None) -> dict:
    """Run the full investigation pipeline via LangGraph StateGraph.

    Executes nodes 1-7, then pauses at interrupt_before on node 8 (human_gate).
    State is persisted to the checkpointer for crash recovery.

    Returns dict matching the original API: run_id, thread_id, alert_id,
    disposition, state, ml_scores, verifier_result, injection_scan.
    """
    graph = _get_graph()
    thread_id = thread_id or f"investigate-{alert_id}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke(
        {"alert_id": alert_id, "thread_id": thread_id},
        config,
    )

    return {
        "run_id": result.get("run_id", ""),
        "thread_id": result.get("thread_id", thread_id),
        "alert_id": alert_id,
        "disposition": result.get("disposition", ""),
        "state": "AWAITING_HUMAN_REVIEW",
        "ml_scores": result.get("ml_scores", {}),
        "verifier_result": result.get("verifier_result", {}),
        "injection_scan": result.get("injection_scan", {}),
        "token_cost": result.get("token_cost", {}),
        "pii_mask_counts": result.get("pii_mask_counts", {}),
    }


def review(alert_id: str, run_id: str, analyst_id: str,
           decision: str, rationale: str = "") -> dict:
    """Node 8 finalize with staleness check. Returns finalized | rerun_triggered.

    Operates directly on the database (not through the graph) to maintain
    synchronous backward compatibility. Writes to audit.human_decisions.
    """
    valid = ("ESCALATE", "CLOSE", "REQUEST_RERUN", "RETURN_FOR_RERUN")
    if decision not in valid:
        raise ValueError(f"decision must be one of {valid}")
    norm = "REQUEST_RERUN" if decision == "RETURN_FOR_RERUN" else decision
    con = connect()
    try:
        cur = con.cursor()
        run_row = _row(cur, f"SELECT * FROM {t('investigation_runs')} WHERE run_id=?", (run_id,))  # nosec B608 - table name from fixed t() whitelist, all values bound
        if not run_row:
            raise KeyError(f"run not found: {run_id}")
        alert = _row(cur, f"SELECT * FROM {t('alerts')} WHERE alert_id=?", (alert_id,))  # nosec B608 - table name from fixed t() whitelist, all values bound
        txs = _rows(cur, f"SELECT tx_id FROM {t('transactions')} WHERE src_account=? OR dst_account=? ORDER BY ts",  # nosec B608 - table name from fixed t() whitelist, all values bound
                    (alert["account_id"], alert["account_id"]))
        latest = txs[-1]["tx_id"] if txs else ""
        stored_mark = run_row["tx_watermark"]
        stale = bool(latest and stored_mark and latest != stored_mark)
        if stale:
            did = uuid.uuid4().hex
            run(cur, f"INSERT INTO {t('human_decisions')} "  # nosec B608 - table name from fixed t() whitelist, all values bound
                  f"(decision_id, run_id, alert_id, analyst_id, decision, rationale, stale_rerun) "
                  f"VALUES (?,?,?,?,?,?,?)",
                  (did, run_id, alert_id, analyst_id, "REQUEST_RERUN",
                   f"stale: watermark {stored_mark} != {latest}. {rationale}", True))
            if hasattr(con, "commit"):
                con.commit()
            audit.log_security_event(
                case_id=alert_id, owasp_category=audit.ASI09,
                action_taken="HITL_RERUN_TRIGGERED",
                details={"run_id": run_id, "analyst_id": analyst_id, "stale": True},
            )
            return {"status": "rerun_triggered", "stale": True, "latest_tx": latest}
        did = uuid.uuid4().hex
        run(cur, f"INSERT INTO {t('human_decisions')} "  # nosec B608 - table name from fixed t() whitelist, all values bound
              f"(decision_id, run_id, alert_id, analyst_id, decision, rationale, stale_rerun) "
              f"VALUES (?,?,?,?,?,?,?)",
              (did, run_id, alert_id, analyst_id, norm, rationale or norm, False))
        if hasattr(con, "commit"):
            con.commit()
        audit.log_security_event(
            case_id=alert_id, owasp_category=audit.ASI09,
            action_taken=f"HITL_{norm}",
            details={"run_id": run_id, "analyst_id": analyst_id,
                     "decision_id": did, "stale": False},
        )
        return {"status": "finalized", "stale": False, "decision_id": did}
    finally:
        con.close()
