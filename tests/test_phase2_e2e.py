"""Phase 2 gate: end-to-end investigation incl. staleness + audit immutability.

Integration style: runs against the dev DB (./data/omniguard.db). Run order:
  python scripts/seed.py && python scripts/train.py && pytest
"""
import pytest

from omniguard import graphs_investigation as gi
from omniguard.db import connect, fetchone, init_db, run, t


@pytest.mark.asyncio
async def test_investigate_demo_alert_writes_audit():
    init_db()
    import subprocess
    import sys

    subprocess.run([sys.executable, "scripts/seed.py"], check=True)
    res = await gi.run_investigation("alert-demo-rapid")
    assert res["state"] == "AWAITING_HUMAN_REVIEW"
    assert res["disposition"] in ("RECOMMEND_ESCALATE", "RECOMMEND_CLOSE", "CONFLICT_HUMAN_REVIEW")
    assert res["verifier_result"]["citations_valid"] is True
    # audit row persisted
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT COUNT(*) AS n FROM {t('investigation_runs')} WHERE run_id=?",
                       (res["run_id"],))
        assert row["n"] == 1
    finally:
        con.close()
    # review finalizes (fresh watermark)
    out = gi.review("alert-demo-rapid", res["run_id"], "analyst-1", "ESCALATE", "looks layered")
    assert out["status"] == "finalized"


@pytest.mark.asyncio
async def test_injection_alert_quarantined():
    res = await gi.run_investigation("alert-demo-inject")
    assert res["injection_scan"]["quarantined"] is True
    assert res["disposition"] == "CONFLICT_HUMAN_REVIEW"


def test_audit_immutable():
    with pytest.raises(Exception):
        con = connect()
        try:
            cur = con.cursor()
            row = fetchone(cur, f"SELECT run_id FROM {t('investigation_runs')} LIMIT 1")
            run(cur, f"DELETE FROM {t('investigation_runs')} WHERE run_id=?", (row["run_id"],))
            if hasattr(con, "commit"):
                con.commit()
        finally:
            con.close()
