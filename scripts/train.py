"""Train ML models (Phase 5C): honest split by account + held-out metrics.

Usage: python scripts/train.py [--test-size 0.25]
Reads the ledger, builds per-account-window feature rows, labels from
is_laundering touch, splits TRAIN/TEST by account (GroupShuffleSplit —
no leakage across the split), reports held-out P/R/F1 for flat+graph AND
flat-only (graph-lift check), trains the shipped model on FULL data,
saves to ./models, logs everything to MLflow.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import features as feat  # noqa: E402
from omniguard import graph_features as gf  # noqa: E402
from omniguard import ml  # noqa: E402
from omniguard.config import settings  # noqa: E402
from omniguard.db import connect, t  # noqa: E402
from omniguard.db import run as qrun  # noqa: E402


def load_ledger() -> tuple[list[dict], set[str]]:
    con = connect()
    try:
        cur = con.cursor()
        qrun(cur, f"SELECT * FROM {t('transactions')} ORDER BY ts")
        cols = [d[0] for d in cur.description]
        txs = [dict(zip(cols, list(r))) for r in cur.fetchall()]
        qrun(cur, f"SELECT account_id FROM {t('accounts')} WHERE high_risk_jurisdiction IS TRUE")
        hrs = {r[0] for r in cur.fetchall()}
        return txs, hrs
    finally:
        con.close()


def build_rows(txs: list[dict], hrs: set[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    by_acct: dict[str, list[dict]] = defaultdict(list)
    for tx in txs:
        by_acct[tx["src_account"]].append(tx)
        by_acct[tx["dst_account"]].append(tx)
    X, y, groups = [], [], []
    for acct, rows in by_acct.items():
        if len(rows) < 3:
            continue
        f = feat.compute_features(rows, acct, hrs)
        g = gf.compute_graph_features(rows, acct, hrs)
        X.append(ml.to_vector(f, g))
        y.append(1 if any(r.get("is_laundering") in (1, True) for r in rows) else 0)
        groups.append(acct)
    return np.array(X, dtype=float), np.array(y, dtype=int), groups


def main(test_size: float = 0.25) -> None:
    from sklearn.metrics import f1_score, precision_score, recall_score
    from sklearn.model_selection import GroupShuffleSplit

    from omniguard.ml import _supervised_model

    txs, hrs = load_ledger()
    X, y, groups = build_rows(txs, hrs)
    print(f"windows n={len(y)} pos_rate={y.mean():.3f} accounts={len(set(groups))}")
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=42)
    tr, te = next(gss.split(X, y, groups))
    Xtr, Xte, ytr, yte = X[tr], X[te], y[tr], y[te]

    rep = {"held_out_n": int(len(yte)), "held_out_pos_rate": round(float(yte.mean()), 3)}
    f1_by_family = {}
    for fam in ("lightgbm", "histgb_fallback"):
        for name, cols in (("flat_graph", slice(None)), ("flat_only", slice(0, 12))):
            m, _ = _supervised_model(fam)
            m.fit(Xtr[:, cols], ytr)
            p = m.predict(Xte[:, cols])
            rep[f"{fam}_{name}_P"] = round(float(precision_score(yte, p, zero_division=0)), 3)
            rep[f"{fam}_{name}_R"] = round(float(recall_score(yte, p, zero_division=0)), 3)
            rep[f"{fam}_{name}_F1"] = round(float(f1_score(yte, p, zero_division=0)), 3)
            print(f"held-out {fam} {name}: P={rep[f'{fam}_{name}_P']} "
                  f"R={rep[f'{fam}_{name}_R']} F1={rep[f'{fam}_{name}_F1']}")
        f1_by_family[fam] = rep[f"{fam}_flat_graph_F1"]
    winner = max(f1_by_family, key=f1_by_family.get)
    print(f"shipping {winner} (held-out F1 {f1_by_family[winner]})")
    rep["shipped_family"] = winner

    meta = ml.train(X, y, family=winner)  # shipped model trains on FULL data
    print(f"shipped model trained on n={len(y)} model={meta['model_type']}")
    try:
        import mlflow

        mlflow.set_tracking_uri(str(settings.MLFLOW_TRACKING_URI))
        with mlflow.start_run(run_name="train_split"):
            mlflow.log_params({"model_type": meta["model_type"], "n": len(y), "test_size": test_size})
            mlflow.log_metrics(rep)
    except Exception:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-size", type=float, default=0.25)
    main(**vars(ap.parse_args()))
