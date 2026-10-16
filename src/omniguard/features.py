"""Deterministic feature engine (Graph1 Node 1). Pure Python/SQL math — no LLM.

Features per alert window (all amounts exact, rounded only at the edge):
- n_txs, total_in, total_out, net_flow
- max_amount, mean_amount
- pass_through_ratio: min(total_in,total_out)/max(total_in,total_out) in [0,1]
- velocity_24h: max tx count in any rolling 24h window
- night_ratio: share of txs with UTC hour < 6 or >= 22
- structuring_flags: count of amounts in [9000,10000)
- new_counterparty_ratio: share of counterparties seen once
- high_risk_touch: 1 if any counterparty account is high-risk jurisdiction
"""
from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timedelta


def _parse_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v
    s = str(v)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def compute_features(txs: list[dict], account_id: str, high_risk_accounts: set[str] | None = None) -> dict:
    high_risk_accounts = high_risk_accounts or set()
    txs = sorted(txs, key=lambda r: _parse_ts(r["ts"]))
    n = len(txs)
    if n == 0:
        return {
            "n_txs": 0, "total_in": 0.0, "total_out": 0.0, "net_flow": 0.0,
            "max_amount": 0.0, "mean_amount": 0.0, "pass_through_ratio": 0.0,
            "velocity_24h": 0, "night_ratio": 0.0, "structuring_flags": 0,
            "new_counterparty_ratio": 0.0, "high_risk_touch": 0,
        }
    total_in = sum(float(r["amount"]) for r in txs if r.get("dst_account") == account_id)
    total_out = sum(float(r["amount"]) for r in txs if r.get("src_account") == account_id)
    amounts = [float(r["amount"]) for r in txs]
    denom = max(total_in, total_out)
    ptr = (min(total_in, total_out) / denom) if denom > 0 else 0.0

    times = [_parse_ts(r["ts"]) for r in txs]
    q: deque = deque()
    vel = 0
    for t in times:
        q.append(t)
        while q and (t - q[0]) > timedelta(hours=24):
            q.popleft()
        vel = max(vel, len(q))
    night = sum(1 for t in times if t.hour < 6 or t.hour >= 22) / n
    struct = sum(1 for a in amounts if 9000 <= a < 10000)

    cps = [(r.get("dst_account") if r.get("src_account") == account_id else r.get("src_account")) for r in txs]
    counts = Counter(cps)
    new_cp = sum(1 for c in cps if counts[c] == 1) / n
    hr = 1 if any(c in high_risk_accounts for c in cps) else 0

    return {
        "n_txs": n,
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net_flow": round(total_in - total_out, 2),
        "max_amount": round(max(amounts), 2),
        "mean_amount": round(sum(amounts) / n, 2),
        "pass_through_ratio": round(ptr, 4),
        "velocity_24h": vel,
        "night_ratio": round(night, 4),
        "structuring_flags": struct,
        "new_counterparty_ratio": round(new_cp, 4),
        "high_risk_touch": hr,
    }
