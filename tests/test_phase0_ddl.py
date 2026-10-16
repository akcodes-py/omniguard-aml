"""Phase 0 gate: DDL freeze — all PRD Sec 4 tables exist, append-only guards hold."""
import sqlite3

from omniguard.db import SQLITE_DDL


def _fresh():
    con = sqlite3.connect(":memory:")
    con.executescript(SQLITE_DDL.read_text())
    return con


def test_all_tables_exist():
    con = _fresh()
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("accounts", "transactions", "alerts", "graph_features", "policy_notes",
              "investigation_runs", "human_decisions", "model_promotions",
              "risk_concerns", "scenario_sets", "expected_outcomes", "control_runs"):
        assert t in tables, f"missing {t}"


def test_append_only_guards():
    import pytest

    con = _fresh()
    con.execute("INSERT INTO accounts (account_id) VALUES ('a1')")
    con.execute("INSERT INTO alerts (alert_id, account_id, trigger, window_start, window_end)"
                " VALUES ('al1','a1','t','2024-01-01','2024-01-02')")
    con.execute("INSERT INTO investigation_runs (run_id, alert_id, thread_id, tx_watermark, features,"
                " ml_scores, injection_scan, retrieved_policies, verifier_result, disposition,"
                " prompt_version_hash, model_id) VALUES ('r1','al1','th','tx', '{}','{}','{}','[]','{}',"
                " 'CONFLICT_HUMAN_REVIEW','ph','m')")
    with pytest.raises(Exception, match="append-only"):
        con.execute("UPDATE investigation_runs SET disposition='RECOMMEND_CLOSE' WHERE run_id='r1'")
    with pytest.raises(Exception, match="append-only"):
        con.execute("DELETE FROM investigation_runs WHERE run_id='r1'")

def test_run_handles_literal_percent():
    import sqlite3

    from omniguard.db import fetchall, run

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE k (a TEXT)")
    con.executemany("INSERT INTO k VALUES (?)", [("eval-1",), ("other",)])
    cur = con.cursor()
    assert [r["a"] for r in fetchall(cur, "SELECT a FROM k WHERE a LIKE 'eval-%'")] == ["eval-1"]
    esc = "SELECT a FROM k WHERE a LIKE 'eval-%'".replace("%", "%%").replace("?", "%s")
    assert esc == "SELECT a FROM k WHERE a LIKE 'eval-%%'"
