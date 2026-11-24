"""FastAPI surface (PRD Sec 9). Async routes, validation, enqueue only.

Auth: X-API-Key header vs settings.API_KEY (Phase 4 deliverable, on from day 1).
Heavy work runs in worker/fallback queue — routes never block on LLM/ML.
"""
from __future__ import annotations

import re
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import graphs_investigation as gi
from . import graphs_scenario as gs
from . import queue as q
from .config import settings
from .db import connect, fetchall, fetchone, t

app = FastAPI(title="OmniGuard AML", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> str:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


class ReviewBody(BaseModel):
    run_id: str
    analyst_id: str
    decision: str
    notes: str = ""
    rationale: str = ""


class ScenarioBody(BaseModel):
    concern_text: str = Field(min_length=1)
    submitted_by: str = "unknown"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "services": {"api": "up", "queue": "redis" if settings.REDIS_URL else "fallback",
                                         "llm": settings.LLM_PROVIDER}}


@app.get("/auth/check")
def auth_check(_: None = Depends(require_key)) -> dict:
    return {"status": "ok", "auth": "valid"}


@app.post("/investigate/{alert_id}", status_code=202)
async def investigate(alert_id: str, _: None = Depends(require_key)) -> dict:
    job_id = await q.enqueue_investigation(alert_id)
    return {"status": "accepted", "job_id": job_id}


@app.get("/investigate/{alert_id}/status")
async def investigate_status(alert_id: str, _: None = Depends(require_key)) -> dict:
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT run_id, disposition, ml_scores, verifier_result, token_cost,"
                            f" injection_scan, created_at"
                            f" FROM {t('investigation_runs')}"
                            f" WHERE alert_id=? ORDER BY created_at DESC LIMIT 1", (alert_id,))
        if not row:
            return {"state": "no_runs_yet", "alert_id": alert_id}
        return {"state": "AWAITING_HUMAN_REVIEW", "alert_id": alert_id,
                "disposition": row["disposition"], "partial_results": row}
    finally:
        con.close()


@app.post("/investigate/{alert_id}/review")
async def investigate_review(alert_id: str, body: ReviewBody, _: None = Depends(require_key)) -> dict:
    try:
        notes = body.notes or body.rationale
        return gi.review(alert_id, body.run_id, body.analyst_id, body.decision, notes)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/scenario/", status_code=202)
async def scenario_create(body: ScenarioBody, _: None = Depends(require_key)) -> dict:
    cid = gs.ingest(body.concern_text, body.submitted_by)
    job_id = await q.enqueue_scenario(cid)
    return {"concern_id": cid, "job_id": job_id}


@app.get("/scenario/{sid}/status")
async def scenario_status(sid: str, _: None = Depends(require_key)) -> dict:
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT set_id, status, challenger_findings FROM {t('scenario_sets')}"
                            f" WHERE set_id=? OR concern_id=? ORDER BY created_at DESC LIMIT 1", (sid, sid))
        if not row:
            return {"state": "queued", "id": sid}
        return {"state": row["status"], "set_id": row["set_id"],
                "scenarios_generated": True,
                "challenger_findings": row["challenger_findings"]}
    finally:
        con.close()


@app.post("/scenario/{sid}/approve")
async def scenario_approve(sid: str, body: dict, _: None = Depends(require_key)) -> dict:
    res = gs.approve_and_execute(sid)
    return {"status": "executing_control", **res}


_BIZ_TOKENS = {"inc", "llc", "ltd", "corp", "corporation", "group", "plc", "bank",
               "trust", "fund", "capital", "holdings", "partners", "co"}
_BIZ_PURPOSE = {"treasury", "payroll", "settlement", "merchant", "business"}


def _account_kind(acct: dict) -> str:
    """Coarse entity class used for graph glyphs (person | business | card)."""
    name = str(acct.get("customer_name") or "").lower()
    purpose = str(acct.get("account_purpose") or "").lower()
    tokens = set(re.findall(r"[a-z]+", name))
    if tokens & _BIZ_TOKENS or purpose in _BIZ_PURPOSE:
        return "business"
    if acct.get("account_type"):
        at = str(acct["account_type"]).lower()
        if at in {"business", "merchant", "corporate"}:
            return "business"
        if at in {"card", "credit_card", "debit_card"}:
            return "card"
    return "person"


@app.get("/alerts")
def alerts(limit: int = 25, _: None = Depends(require_key)) -> dict:
    """Recent alerts for the graph explorer's search palette."""
    con = connect()
    try:
        cur = con.cursor()
        rows = fetchall(
            cur,
            f"SELECT a.alert_id, a.account_id, a.trigger, a.trigger_reason, a.status,"
            f" a.window_start, a.window_end, c.customer_name"
            f" FROM {t('alerts')} a LEFT JOIN {t('accounts')} c ON c.account_id = a.account_id"
            f" ORDER BY a.created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        return {"alerts": rows}
    finally:
        con.close()


@app.get("/graph/{alert_id}")
def graph(alert_id: str, _: None = Depends(require_key)) -> dict:
    """Entity graph + transaction ledger for one alert.

    Nodes/edges are derived from the alert account's transaction
    neighbourhood; the panel summary and latest transactions ride along.
    """
    con = connect()
    try:
        cur = con.cursor()
        alert = fetchone(cur, f"SELECT * FROM {t('alerts')} WHERE alert_id=?", (alert_id,))
        if not alert:
            raise HTTPException(status_code=404, detail="alert not found")
        acct_id = alert["account_id"]
        focal = fetchone(cur, f"SELECT * FROM {t('accounts')} WHERE account_id=?", (acct_id,)) or {
            "account_id": acct_id, "customer_name": acct_id,
        }
        txs = fetchall(
            cur,
            f"SELECT * FROM {t('transactions')} WHERE src_account=? OR dst_account=? ORDER BY ts DESC",
            (acct_id, acct_id),
        )
        ids = sorted({r["src_account"] for r in txs} | {r["dst_account"] for r in txs})
        accts: dict[str, dict] = {}
        if ids:
            ph = ",".join("?" for _ in ids)
            for a in fetchall(cur, f"SELECT * FROM {t('accounts')} WHERE account_id IN ({ph})", tuple(ids)):
                accts[a["account_id"]] = a
        accts.setdefault(acct_id, focal)

        laundering_accts = {
            r["dst_account"] if r["src_account"] == acct_id else r["src_account"]
            for r in txs if r.get("is_laundering")
        }

        nodes: dict[str, dict] = {}
        for aid in ids:
            a = accts.get(aid, {"account_id": aid})
            related = [r for r in txs if aid in (r["src_account"], r["dst_account"])]
            nodes[aid] = {
                "id": aid,
                "label": a.get("customer_name") or aid,
                "kind": _account_kind(a),
                "account_purpose": a.get("account_purpose"),
                "jurisdiction": a.get("risk_jurisdiction"),
                "high_risk": bool(a.get("high_risk_jurisdiction")) or aid in laundering_accts,
                "is_focal": aid == acct_id,
                "tx_count": len(related),
                "amount_total": round(sum(float(r["amount"] or 0) for r in related), 2),
            }
        if acct_id not in nodes:
            nodes[acct_id] = {
                "id": acct_id, "label": focal.get("customer_name") or acct_id,
                "kind": _account_kind(focal), "account_purpose": focal.get("account_purpose"),
                "jurisdiction": focal.get("risk_jurisdiction"),
                "high_risk": bool(focal.get("high_risk_jurisdiction")),
                "is_focal": True, "tx_count": 0, "amount_total": 0.0,
            }

        pairs: dict[tuple[str, str], dict] = {}
        for r in txs:
            key = (r["src_account"], r["dst_account"])
            p = pairs.setdefault(key, {
                "id": f"{key[0]}->{key[1]}", "source": key[0], "target": key[1],
                "amount": 0.0, "count": 0, "channels": set(), "laundering": False,
            })
            p["amount"] += float(r["amount"] or 0)
            p["count"] += 1
            if r.get("channel"):
                p["channels"].add(str(r["channel"]))
            p["laundering"] = p["laundering"] or bool(r.get("is_laundering"))
        edges = []
        for p in pairs.values():
            p["amount"] = round(p["amount"], 2)
            p["channels"] = sorted(p["channels"])
            edges.append(p)
        edges.sort(key=lambda e: e["amount"], reverse=True)

        amounts = [float(r["amount"] or 0) for r in txs]
        inflow = sum(float(r["amount"] or 0) for r in txs if r["dst_account"] == acct_id)
        outflow = sum(float(r["amount"] or 0) for r in txs if r["src_account"] == acct_id)
        recent = [
            {
                "tx_id": r["tx_id"], "ts": r["ts"], "amount": round(float(r["amount"] or 0), 2),
                "currency": r.get("currency") or "USD", "channel": r.get("channel"),
                "tx_type": r.get("tx_type"), "memo": r.get("memo"),
                "direction": "IN" if r["dst_account"] == acct_id else "OUT",
                "counterparty": r["src_account"] if r["dst_account"] == acct_id else r["dst_account"],
                "counterparty_name": (accts.get(r["src_account"] if r["dst_account"] == acct_id else r["dst_account"]) or {}).get("customer_name"),
            }
            for r in txs[:12]
        ]
        return {
            "alert": alert,
            "focal": nodes.get(acct_id),
            "nodes": list(nodes.values()),
            "edges": edges,
            "summary": {
                "tx_count": len(txs),
                "tx_capacity": len(txs),
                "amount_total": round(sum(amounts), 2),
                "amount_capacity": round(sum(amounts), 2),
                "inflow": round(inflow, 2),
                "outflow": round(outflow, 2),
                "max_amount": round(max(amounts), 2) if amounts else 0.0,
                "high_risk_nodes": sum(1 for n in nodes.values() if n["high_risk"]),
            },
            "transactions": recent,
        }
    finally:
        con.close()


@app.get("/scenario/{sid}/results")
async def scenario_results(sid: str, _: None = Depends(require_key)) -> dict:
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT * FROM {t('control_runs')} WHERE set_id=? ORDER BY created_at DESC LIMIT 1",
                       (sid,))
        if not row:
            raise HTTPException(status_code=404, detail="no control runs yet")
        return row
    finally:
        con.close()
