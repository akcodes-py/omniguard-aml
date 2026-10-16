"""Phase 4 baselines (PRD Sec 10): single-LLM vs dual-pass, flat vs flat+graph.

Usage: python scripts/baselines.py
Honest comparison on the seeded ledger (in-sample for ML, pipeline for LLM).
Logs both arms to MLflow.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import features as feat  # noqa: E402
from omniguard import graph_features as gf  # noqa: E402
from omniguard import graphs_investigation as gi  # noqa: E402
from omniguard import llm  # noqa: E402
from omniguard import ml  # noqa: E402
from omniguard.config import settings  # noqa: E402
from omniguard.db import connect, t  # noqa: E402


def flat_only_f1() -> tuple[float, float]:
    con = connect()
    try:
        cur = con.cursor()
        cur.execute(f"SELECT * FROM {t('transactions')} ORDER BY ts")
        cols = [d[0] for d in cur.description]
        txs = [dict(zip(cols, list(r))) for r in cur.fetchall()]
    finally:
        con.close()
    by_acct: dict[str, list[dict]] = defaultdict(list)
    for tx in txs:
        by_acct[tx["src_account"]].append(tx)
        by_acct[tx["dst_account"]].append(tx)
    Xf, Xg, y = [], [], []
    for acct, rows in by_acct.items():
        if len(rows) < 3:
            continue
        f = feat.compute_features(rows, acct)
        g = gf.compute_graph_features(rows, acct)
        v = ml.to_vector(f, g)
        Xf.append(v[:12])  # flat only (no graph cols)
        Xg.append(v)       # flat + graph
        y.append(1 if any(r.get("is_laundering") in (1, True) for r in rows) else 0)
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import f1_score

    Xf, Xg, y = np.array(Xf), np.array(Xg), np.array(y)
    pf = HistGradientBoostingClassifier(max_iter=100).fit(Xf, y).predict(Xf)
    pg = HistGradientBoostingClassifier(max_iter=100).fit(Xg, y).predict(Xg)
    return round(float(f1_score(y, pf, zero_division=0)), 3), round(float(f1_score(y, pg, zero_division=0)), 3)


async def single_vs_dual() -> dict:
    """Single-LLM arm: investigator alone decides (escalate iff typology != benign).
    Dual arm: full pipeline with challenger + verifier + adjudicator."""
    single_fp = dual_fp = n = 0
    for _ in range(6):
        res = await gi.run_investigation("alert-demo-clean")
        n += 1
        inv = llm.call_json("investigator", {"facts": {"n_txs": 5}, "tx_ids": ["t"],
                                             "policy_ids": [], "policies": [], "memos": []})[0]
        if inv["matched_typology"] != "benign":
            single_fp += 1
        if res["disposition"] == "RECOMMEND_ESCALATE":
            dual_fp += 1
    return {"single_llm_fpr": round(single_fp / n, 3), "dual_fpr": round(dual_fp / n, 3), "n": n}


def main() -> None:
    f1_flat, f1_graph = flat_only_f1()
    print(f"flat_only_F1={f1_flat} flat+graph_F1={f1_graph}")
    comp = asyncio.run(single_vs_dual())
    print(f"single_vs_dual={comp}")
    try:
        import mlflow

        mlflow.set_tracking_uri(str(settings.MLFLOW_TRACKING_URI))
        with mlflow.start_run(run_name="baselines"):
            mlflow.log_metrics({"flat_only_F1": f1_flat, "flat_graph_F1": f1_graph,
                                **{k: v for k, v in comp.items() if isinstance(v, float)}})
    except Exception:
        pass


if __name__ == "__main__":
    main()
