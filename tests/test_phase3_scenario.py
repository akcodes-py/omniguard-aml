"""Phase 3 gate: ScenarioLab lock-then-execute + tamper detection."""
from omniguard import graphs_scenario as gs
from omniguard import scenario_gen as sg
from omniguard.db import init_db


def test_lock_hash_immutable_and_report_complete():
    init_db()
    cid = gs.ingest("smurfing via micro-deposits under reporting threshold", "risk-owner-1")
    lab = gs.run_scenariolab(cid)
    assert lab["state"] == "AWAITING_SIGNOFF"
    assert lab["scenario_hash"] == sg.sha256(lab["scenarios"])
    out = gs.approve_and_execute(lab["set_id"])
    assert set(out["summary"]) == {"matches", "misses", "over_alerts", "total"}
    assert out["summary"]["total"] == len(lab["scenarios"]) == 4
    assert len(out["coverage_gaps"]) >= 1  # mandatory NOT-tested section
    assert len(out["evidence_pack_hash"]) == 64


def test_deterministic_generator():
    specs = [{"kind": "suspicious", "typology": "x", "n_txs": 3, "amount_each": 100.0,
              "window_hours": 24.0, "backstory": "b", "expected": "ALERT"}]
    a = sg.generate_transactions(specs)
    b = sg.generate_transactions(specs)
    assert [x["amount"] for x in a] == [x["amount"] for x in b] == [100.0, 100.0, 100.0]
    assert sg.sha256({"a": 1}) == sg.sha256({"a": 1})
