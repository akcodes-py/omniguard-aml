"""ScenarioLab deterministic core (Graph2 Nodes 3,4,7,8). No LLM here.

- generate_transactions(): Pydantic specs -> exact tx rows (correct math/timestamps).
- lock(): SHA-256 of canonical JSON for scenario sets + expected outcomes.
- execute_control(): sample 48h pass-through rule in pure code.
- compare(): MATCH / MISS / OVER-ALERT + summary + mandatory NOT-tested gaps.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone


def canonical(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


def sha256(o) -> str:
    return hashlib.sha256(canonical(o).encode()).hexdigest()


def generate_transactions(specs: list[dict], base_ts: datetime | None = None) -> list[dict]:
    base_ts = base_ts or datetime(2024, 1, 1, tzinfo=timezone.utc)
    txs: list[dict] = []
    for i, s in enumerate(specs):
        n = int(s.get("n_txs", 1))
        amt = float(s.get("amount_each", 0.0))
        window_h = float(s.get("window_hours", 48.0))
        step = timedelta(hours=window_h / max(n, 1))
        acct = f"acct-scen-{i}"
        for j in range(n):
            txs.append({
                "tx_id": f"scen-{i}-{j}-{uuid.uuid4().hex[:6]}",
                "ts": (base_ts + j * step).isoformat(),
                "src_account": acct,
                "dst_account": f"cp-{i}-{j}",
                "amount": round(amt, 2),
                "currency": "USD",
                "direction": "OUT",
                "tx_type": "transfer",
                "channel": "wire",
                "memo": f"{s.get('typology','transfer')} {s.get('backstory','')}"[:200],
                "counterparty_name": f"cp-{i}-{j}",
                "scenario_idx": i,
            })
    return txs


def lock_expectations(specs: list[dict]) -> tuple[dict, str]:
    exp = {str(i): ("ALERT" if s.get("expected") == "ALERT" else "NO_ALERT") for i, s in enumerate(specs)}
    return exp, sha256(exp)


def execute_control_48h_passthrough(txs: list[dict], window_h: float = 48.0) -> dict[int, str]:
    """Sample control: ALERT if an account passes >=80% through within window_h."""
    from collections import defaultdict

    by_acct: dict[str, list[dict]] = defaultdict(list)
    for tx in txs:
        by_acct[tx["src_account"]].append(tx)
    out: dict[int, str] = {}
    idxs = sorted({tx.get("scenario_idx", 0) for tx in txs})
    for i in idxs:
        rows = [tx for tx in txs if tx.get("scenario_idx") == i]
        if not rows:
            out[i] = "NO_ALERT"
            continue
        total = sum(float(r["amount"]) for r in rows)
        span = (max(r["ts"] for r in rows) > min(r["ts"] for r in rows))
        flagged = total >= 20000 and span
        out[i] = "ALERT" if flagged else "NO_ALERT"
    return out


def compare(expected: dict, actual: dict) -> tuple[dict, dict]:
    results, m = {}, {"matches": 0, "misses": 0, "over_alerts": 0, "total": len(expected)}
    for k, exp in expected.items():
        act = actual.get(int(k), actual.get(k, "NO_ALERT"))
        verdict = "MATCH" if exp == act else ("MISS" if exp == "ALERT" else "OVER-ALERT")
        m[{"MATCH": "matches", "MISS": "misses", "OVER-ALERT": "over_alerts"}[verdict]] += 1
        results[k] = {"expected": exp, "actual": act, "verdict": verdict}
    return results, m


COVERAGE_GAPS_DEFAULT = [
    "cross-border correspondent banking not tested",
    "cash structuring under $3k not tested",
    "multi-hop (>2) layering beyond generator window not tested",
]
