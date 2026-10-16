"""Job queue: ARQ/Redis when REDIS_URL set, else in-process asyncio fallback.

Same enqueue API either way so api.py stays transport-free. Local runs use
the fallback (no Redis installed here); docker-compose uses ARQ.
"""
from __future__ import annotations

import asyncio
import uuid

from .config import settings

_FALLBACK_JOBS: dict[str, dict] = {}


async def enqueue_investigation(alert_id: str) -> str:
    job_id = uuid.uuid4().hex
    if settings.REDIS_URL:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        try:
            job = await pool.enqueue_job("run_investigation_job", alert_id)
            return job.job_id
        finally:
            await pool.close()
    _FALLBACK_JOBS[job_id] = {"kind": "investigate", "alert_id": alert_id, "state": "queued"}
    asyncio.get_running_loop().call_later(0, lambda: asyncio.ensure_future(_run_fallback(job_id)))
    return job_id


async def _run_fallback(job_id: str) -> None:
    from . import graphs_investigation as gi

    job = _FALLBACK_JOBS.get(job_id)
    if not job:
        return
    try:
        job["state"] = "in_progress"
        if job["kind"] == "investigate":
            job["result"] = await gi.run_investigation(job["alert_id"])
            job["state"] = "done"
        elif job["kind"] == "scenario":
            from . import graphs_scenario as gs

            job["result"] = gs.run_scenariolab(job["concern_id"])
            job["state"] = "done"
    except Exception as e:  # noqa: BLE001
        job["state"] = "failed"
        job["error"] = str(e)


async def enqueue_scenario(concern_id: str) -> str:
    job_id = uuid.uuid4().hex
    if settings.REDIS_URL:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        try:
            job = await pool.enqueue_job("run_scenario_job", concern_id)
            return job.job_id
        finally:
            await pool.close()
    _FALLBACK_JOBS[job_id] = {"kind": "scenario", "concern_id": concern_id, "state": "queued"}
    asyncio.get_running_loop().call_later(0, lambda: asyncio.ensure_future(_run_fallback(job_id)))
    return job_id


def get_job(job_id: str) -> dict | None:
    return _FALLBACK_JOBS.get(job_id)
