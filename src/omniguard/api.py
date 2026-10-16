"""FastAPI surface (PRD Sec 9). Async routes, validation, enqueue only.

Auth: X-API-Key header vs settings.API_KEY (Phase 4 deliverable, on from day 1).
Heavy work runs in worker/fallback queue — routes never block on LLM/ML.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import graphs_investigation as gi
from . import graphs_scenario as gs
from . import queue as q
from .config import settings
from .db import connect, fetchone, t

app = FastAPI(title="OmniGuard AML", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_key(x_api_key: str = Header(default="")) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "services": {"api": "up", "queue": "redis" if settings.REDIS_URL else "fallback",
                                         "llm": settings.LLM_PROVIDER}}


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
async def investigate_review(alert_id: str, body: dict, _: None = Depends(require_key)) -> dict:
    try:
        return gi.review(alert_id, body["run_id"], body["analyst_id"],
                         body["decision"], body.get("notes", body.get("rationale", "")))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/scenario/", status_code=202)
async def scenario_create(body: dict, _: None = Depends(require_key)) -> dict:
    cid = gs.ingest(body["concern_text"], body.get("submitted_by", "unknown"))
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
