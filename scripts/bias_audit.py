"""Slice-level false-positive parity check on the simulated ledger.

Usage:  python scripts/bias_audit.py [--out data/bias_audit.json]

Builds one case per account from the seeded synthetic ledger, scores it with
the same deterministic feature/ML path as the investigation graph, and
compares false-positive rates (FPR) across transaction-amount tiers and
customer segments. Parity threshold: |slice FPR - overall FPR| <= 0.10.

No protected attributes exist in the simulated dataset; purpose and
jurisdiction are *proxies* only. Results are a monitoring signal, not a
fairness guarantee. See MODEL_CARD.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import features as feat  # noqa: E402
from omniguard import graph_features as gf  # noqa: E402
from omniguard import ml  # noqa: E402
from omniguard.config import settings  # noqa: E402
from omniguard.db import connect, fetchall  # noqa: E402

PARITY_TOLERANCE = 0.10


def _amount_tier(mean_amount: float) -> str:
    if mean_amount < 1000:
        return "low (<1k)"
    if mean_amount < 10000:
        return "mid (1k-10k)"
    return "high (>=10k)"


def _segment(account: dict) -> str:
    return str(account.get("account_purpose") or "unknown")


def _score(vec: list[float]) -> float:
    try:
        return float(ml.score(vec)["composite"])
    except (FileNotFoundError, Exception):  # noqa: BLE001 - offline/untrained fallback
        return min(0.95, 0.15 + 0.6 * vec[6] + 0.05 * vec[9])


def build_cases() -> list[dict]:
    con = connect()
    try:
        cur = con.cursor()
        accounts = fetchall(cur, "SELECT * FROM accounts")
        txs = fetchall(cur, "SELECT * FROM transactions")
    finally:
        con.close()
    by_id = {a["account_id"]: a for a in accounts}
    hr = {a["account_id"] for a in accounts if a.get("high_risk_jurisdiction")}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for tx in txs:
        grouped[str(tx["src_account"])].append(tx)
        grouped[str(tx["dst_account"])].append(tx)

    cases = []
    for account_id, account_txs in sorted(grouped.items()):
        account = by_id.get(account_id, {})
        f = feat.compute_features(account_txs, account_id, hr)
        g = gf.compute_graph_features(account_txs, account_id, hr)
        composite = _score(ml.to_vector(f, g))
        cases.append({
            "account_id": account_id,
            "label": any(bool(tx.get("is_laundering")) for tx in account_txs),
            "predicted_alert": composite >= settings.ESCALATE_THRESHOLD,
            "composite": round(composite, 4),
            "amount_tier": _amount_tier(float(f["mean_amount"])),
            "segment": _segment(account),
            "high_risk_jurisdiction": bool(account_id in hr),
        })
    return cases


def _fpr(rows: list[dict]) -> dict:
    negatives = [r for r in rows if not r["label"]]
    fp = sum(1 for r in negatives if r["predicted_alert"])
    tn = len(negatives) - fp
    return {
        "n": len(rows), "negatives": len(negatives), "fp": fp, "tn": tn,
        "fpr": round(fp / (fp + tn), 4) if (fp + tn) else None,
    }


def audit() -> dict:
    cases = build_cases()
    overall = _fpr(cases)
    slices: dict[str, dict] = {}
    for dimension in ("amount_tier", "segment", "high_risk_jurisdiction"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for case in cases:
            groups[str(case[dimension])].append(case)
        for name, rows in sorted(groups.items()):
            stat = _fpr(rows)
            gap = (abs(stat["fpr"] - overall["fpr"])
                   if stat["fpr"] is not None and overall["fpr"] is not None else None)
            stat["gap_vs_overall"] = round(gap, 4) if gap is not None else None
            stat["parity_ok"] = gap is None or gap <= PARITY_TOLERANCE
            slices[f"{dimension}={name}"] = stat
    return {
        "dataset": "simulated PaySim-like ledger (scripts/seed.py, seed=42)",
        "decision_rule": f"composite >= {settings.ESCALATE_THRESHOLD} (HITL still required)",
        "parity_tolerance": PARITY_TOLERANCE,
        "n_cases": len(cases),
        "overall": overall,
        "slices": slices,
        "slices_failing_parity": [k for k, v in slices.items() if not v["parity_ok"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="optional path to write the JSON report")
    args = ap.parse_args()
    report = audit()
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
