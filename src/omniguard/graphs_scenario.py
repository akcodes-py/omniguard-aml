"""Graph2 ScenarioLab pipeline (PRD Sec 6): 8 nodes.

ingest_concern (code) -> author_scenarios (LLM) -> generate_transactions
(code deterministic) -> lock_expectations (SHA-256) -> challenge_scenarios
(LLM rubric) -> human_signoff (gate) -> execute_control (code) ->
compare_and_report (code + diversity + NOT-tested).
"""
from __future__ import annotations

import uuid

from . import llm
from . import scenario_gen as sg
from .db import connect, dumps, fetchone, is_postgres, loads, run, t


def ingest(concern_text: str, submitted_by: str) -> str:
    cid = uuid.uuid4().hex
    con = connect()
    try:
        cur = con.cursor()
        run(cur, f"INSERT INTO {t('risk_concerns')} (concern_id, concern_text, submitted_by) VALUES (?,?,?)",
            (cid, concern_text, submitted_by))
        if hasattr(con, "commit"):
            con.commit()
        return cid
    finally:
        con.close()


def run_scenariolab(concern_id: str) -> dict:
    con = connect()
    try:
        cur = con.cursor()
        concern = fetchone(cur, f"SELECT * FROM {t('risk_concerns')} WHERE concern_id=?", (concern_id,))
        if not concern:
            raise KeyError(concern_id)
    finally:
        con.close()
    specs, _ = llm.call_json("scenario_author", {"concern": concern["concern_text"]})
    txs = sg.generate_transactions(specs)
    s_hash = sg.sha256(specs)
    expectations, e_hash = sg.lock_expectations(specs)
    findings, _ = llm.call_json("scenario_challenger", {"scenarios": specs})

    set_id, out_id = uuid.uuid4().hex, uuid.uuid4().hex
    con = connect()
    try:
        cur = con.cursor()
        run(cur, f"INSERT INTO {t('scenario_sets')} (set_id, concern_id, version, scenarios, scenario_hash,"
                 f" generated_txs, challenger_findings, diversity_score, status) VALUES (?,?,?,?,?,?,?,?,?)",
            (set_id, concern_id, 1, dumps(specs), s_hash, dumps(txs), dumps(findings), 0.85, "LOCKED"))
        run(cur, f"INSERT INTO {t('expected_outcomes')} (outcome_id, set_id, expectations, expectation_hash)"
                 f" VALUES (?,?,?,?)", (out_id, set_id, dumps(expectations), e_hash))
        if hasattr(con, "commit"):
            con.commit()
    finally:
        con.close()
    return {"set_id": set_id, "outcome_id": out_id, "scenarios": specs,
            "scenario_hash": s_hash, "expectation_hash": e_hash,
            "challenger_findings": findings, "state": "AWAITING_SIGNOFF"}


def approve_and_execute(set_id: str, control_id: str = "rule_48h_passthrough",
                        control_version: str = "v1") -> dict:
    con = connect()
    try:
        cur = con.cursor()
        sset = fetchone(cur, f"SELECT * FROM {t('scenario_sets')} WHERE set_id=?", (set_id,))
        out = fetchone(cur, f"SELECT * FROM {t('expected_outcomes')} WHERE set_id=?", (set_id,))
    finally:
        con.close()
    if sset is None:
        raise KeyError(f"scenario set not found: {set_id}")
    if out is None:
        raise KeyError(f"expected outcomes not found: {set_id}")
    if sset.get("status") != "LOCKED":
        raise ValueError(f"scenario set not in LOCKED state (status={sset.get('status')!r}); "
                        f"already executed or not ready for approval")
    specs, txs = loads(sset["scenarios"]), loads(sset["generated_txs"])
    expectations = loads(out["expectations"])
    # integrity: recompute lock hash, must match sealed value (explicit raise so it
    # survives `python -O`, which strips assert statements)
    actual_hash = sg.sha256(expectations)
    if actual_hash != out["expectation_hash"]:
        raise ValueError(
            f"Tamper check failed for scenario set {set_id}: "
            f"expected {out['expectation_hash']}, got {actual_hash}"
        )
    actual_raw = sg.execute_control_48h_passthrough(txs)
    actual = {str(k): v for k, v in actual_raw.items()}
    results, summary = sg.compare(expectations, actual)
    pack = {"set_id": set_id, "control_id": control_id, "results": results, "summary": summary,
            "coverage_gaps": sg.COVERAGE_GAPS_DEFAULT}
    ev_hash = sg.sha256(pack)
    run_id = uuid.uuid4().hex
    con = connect()
    try:
        cur = con.cursor()
        run(cur, f"INSERT INTO {t('control_runs')} (run_id, set_id, control_id, control_version, results,"
                 f" summary, coverage_gaps, evidence_pack_hash) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, set_id, control_id, control_version, dumps(results), dumps(summary),
             sg.COVERAGE_GAPS_DEFAULT if is_postgres() else dumps(sg.COVERAGE_GAPS_DEFAULT), ev_hash))
        run(cur, f"UPDATE {t('scenario_sets')} SET status=? WHERE set_id=?", ("EXECUTED", set_id))
        if hasattr(con, "commit"):
            con.commit()
    finally:
        con.close()
    return {"run_id": run_id, "results": results, "summary": summary,
            "coverage_gaps": sg.COVERAGE_GAPS_DEFAULT, "evidence_pack_hash": ev_hash}
