"""Phase 5 live eval: N NIM investigations (dual pipeline) + N single-LLM calls.

Usage: LLM_PROVIDER=nim DATABASE_URL=postgresql://... python scripts/live_eval.py [--n 6]
Bounded: 6 cases x (1 dual investigation + 1 single call). Prints a summary
table (dual vs single dispositions, citation fidelity, quarantine rate,
models used, fallback count, token totals). Logs to MLflow. Writes nothing
except audit rows (by design) — metrics print to stdout for the README.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import graphs_investigation as gi  # noqa: E402
from omniguard import llm  # noqa: E402
from omniguard import features as feat  # noqa: E402
from omniguard import injection as inj  # noqa: E402
from omniguard import policy_retrieval as pr  # noqa: E402
from omniguard.config import settings  # noqa: E402

CASES = [
    ("TP", "alert-demo-rapid"),
    ("TN", "alert-demo-clean"),
    ("lookalike", "alert-demo-clean"),
    ("boundary", "alert-demo-clean"),
    ("injection", "alert-demo-inject"),
    ("TP", "alert-demo-rapid"),
]


async def one(category: str, alert_id: str) -> dict:
    res = await gi.run_investigation(alert_id)
    # Fair single arm: the EXACT payload the dual investigator receives
    # (mirrors graphs_investigation nodes 1+3; same facts, ids, policies, memos).
    bundle = gi.fetch_alert(alert_id)
    tx_ids = [r["tx_id"] for r in bundle["txs"]]
    f = feat.compute_features(bundle["txs"], bundle["alert"]["account_id"], bundle["high_risk"])
    tags = [t for t in (
        "rapid_pass_through" if f.get("pass_through_ratio", 0) > 0.8 else "",
        "structuring" if f.get("structuring_flags", 0) > 0 else "",
        "layering" if f.get("night_ratio", 0) > 0.5 else "") if t] + ["general"]
    policies = pr.retrieve(tags, bundle["alert"].get("trigger_reason", ""))
    single_payload = {"facts": f, "tx_ids": tx_ids,
                      "policy_ids": [[p["policy_id"], p["version"]] for p in policies],
                      "policies": [p["title"] for p in policies],
                      "memos": [inj.sandbox("transaction_memo", tx.get("memo")) for tx in bundle["txs"]]}
    inv, inv_tc = llm.call_json("investigator", single_payload)
    vr = res.get("verifier_result", {})
    dual_tc = res.get("token_cost", {})
    return {
        "category": category,
        "disposition": res["disposition"],
        "dual_models": [dual_tc.get("investigator", {}).get("model_id"),
                        dual_tc.get("challenger", {}).get("model_id")],
        "dual_fallback": bool(dual_tc.get("investigator", {}).get("fallback")
                              or dual_tc.get("challenger", {}).get("fallback")),
        "dual_tokens": dual_tc.get("total", 0),
        "citations_valid": bool(vr.get("citations_valid")),
        "quarantined": bool(res.get("injection_scan", {}).get("quarantined")),
        "single_typology": inv["matched_typology"],
        "single_model": inv_tc.get("model_id"),
        "single_tokens": inv_tc.get("total", 0),
    }


async def main(n: int) -> None:
    assert settings.LLM_PROVIDER == "nim", "run with LLM_PROVIDER=nim"
    rows = [await one(c, a) for c, a in CASES[:n]]
    print(f"{'cat':<10}{'dual':<22}{'single_typo':<20}{'cit':<5}{'quar':<5}{'fb':<4}{'tok_dual':<9}{'tok_1'}")
    for r in rows:
        print(f"{r['category']:<10}{r['disposition']:<22}{r['single_typology']:<20}"
              f"{int(r['citations_valid']):<5}{int(r['quarantined']):<5}{int(r['dual_fallback']):<4}"
              f"{r['dual_tokens']:<9}{r['single_tokens']}")
    dual_esc = sum(r["disposition"] == "RECOMMEND_ESCALATE" for r in rows)
    single_fp = sum(r["single_typology"] != "benign" for r in rows
                    if r["category"] in ("TN", "lookalike", "boundary"))
    single_n = sum(1 for r in rows if r["category"] in ("TN", "lookalike", "boundary"))
    print(f"CITATION_FIDELITY={sum(r['citations_valid'] for r in rows) / len(rows):.3f} "
          f"INJECT_QUAR={sum(r['quarantined'] for r in rows if r['category'] == 'injection')}/"
          f"{sum(1 for r in rows if r['category'] == 'injection')} "
          f"DUAL_ESCALATE={dual_esc}/{len(rows)} SINGLE_FP={single_fp}/{single_n} "
          f"FALLBACKS={sum(r['dual_fallback'] for r in rows)} "
          f"TOK_DUAL={sum(r['dual_tokens'] for r in rows)} TOK_SINGLE={sum(r['single_tokens'] for r in rows)}")
    try:
        import mlflow

        mlflow.set_tracking_uri(str(settings.MLFLOW_TRACKING_URI))
        with mlflow.start_run(run_name="live_eval"):
            mlflow.log_metrics({
                "live_citation_fidelity": sum(r["citations_valid"] for r in rows) / len(rows),
                "live_dual_escalate_rate": dual_esc / len(rows),
                "live_single_fp_rate": single_fp / max(single_n, 1),
                "live_fallbacks": sum(r["dual_fallback"] for r in rows),
                "live_tokens_dual": sum(r["dual_tokens"] for r in rows),
                "live_tokens_single": sum(r["single_tokens"] for r in rows)})
    except Exception:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    asyncio.run(main(**vars(ap.parse_args())))
