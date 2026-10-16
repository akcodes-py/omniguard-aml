"""Phase 5B/5D: 50 DISTINCT-case eval (mock LLM, deterministic).

Usage: DATABASE_URL=... python scripts/eval50_v2.py
Reads eval-* alerts (rule_id = TP|TN|LOOKALIKE|BOUNDARY|INJECTION), runs the
full pipeline per case, prints per-category dispositions + fidelity metrics,
logs to MLflow. Mock LLM keeps it free and reproducible; live subset covered
by scripts/live_eval.py.
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import graphs_investigation as gi  # noqa: E402
from omniguard.config import settings  # noqa: E402
from omniguard.db import connect, fetchall, t  # noqa: E402

CATS = ("TP", "TN", "LOOKALIKE", "BOUNDARY", "INJECTION")


async def main(prefix: str = "eval2") -> None:
    con = connect()
    try:
        cur = con.cursor()
        cases = fetchall(cur, f"SELECT alert_id, rule_id FROM {t('alerts')} "
                              f"WHERE alert_id LIKE '{prefix}-%' ORDER BY alert_id")
    finally:
        con.close()
    assert len(cases) == 50, f"expected 50 distinct cases, found {len(cases)}"
    by_cat = defaultdict(list)
    for c in cases:
        try:
            res = await gi.run_investigation(c["alert_id"])
        except Exception as e:  # noqa: BLE001
            print(f"case {c['alert_id']} FAILED: {e}")
            continue
        vr = res.get("verifier_result", {})
        by_cat[c["rule_id"]].append({
            "disp": res["disposition"],
            "cit": bool(vr.get("citations_valid")),
            "quar": bool(res.get("injection_scan", {}).get("quarantined")),
        })
    print(f"{'cat':<10}{'n':<4}{'escalate':<9}{'close':<7}{'conflict':<9}{'cit_fid':<9}{'quar'}")
    tot_cit = tot_n = 0
    for cat in CATS:
        rows = by_cat[cat]
        d = Counter(r["disp"] for r in rows)
        cf = sum(r["cit"] for r in rows) / len(rows)
        qr = sum(r["quar"] for r in rows) / len(rows)
        tot_cit += sum(r["cit"] for r in rows)
        tot_n += len(rows)
        print(f"{cat:<10}{len(rows):<4}{d.get('RECOMMEND_ESCALATE', 0):<9}"
              f"{d.get('RECOMMEND_CLOSE', 0):<7}{d.get('CONFLICT_HUMAN_REVIEW', 0):<9}"
              f"{cf:<9.3f}{qr:.3f}")
    print(f"OVERALL_CITATION={tot_cit / tot_n:.3f} N={tot_n}")
    try:
        import mlflow

        mlflow.set_tracking_uri(str(settings.MLFLOW_TRACKING_URI))
        with mlflow.start_run(run_name="eval50_v2"):
            mlflow.log_metric("citation_fidelity", tot_cit / tot_n)
            for cat in CATS:
                rows = by_cat[cat]
                mlflow.log_metric(f"{cat.lower()}_escalate",
                                  sum(r["disp"] == "RECOMMEND_ESCALATE" for r in rows) / len(rows))
    except Exception:
        pass


if __name__ == "__main__":
    import argparse as _ap

    _p = _ap.ArgumentParser()
    _p.add_argument("--prefix", default="eval2")
    asyncio.run(main(**vars(_p.parse_args())))
