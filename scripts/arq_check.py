"""ARQ live check (Phase 2): enqueue via Redis, drain with burst worker, verify audit row.

Usage (with Postgres + Redis up):
  DATABASE_URL=postgresql://... REDIS_URL=redis://localhost:6379 python scripts/arq_check.py <alert_id>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


async def _enqueue(alert_id: str) -> str:
    from arq import create_pool
    from arq.connections import RedisSettings

    from omniguard.config import settings

    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    try:
        job = await pool.enqueue_job("run_investigation_job", alert_id)
        return job.job_id
    finally:
        await pool.close()


def main(alert_id: str) -> None:
    from arq import run_worker

    from omniguard import worker as w
    from omniguard.db import connect, fetchone, t

    print("enqueued", asyncio.run(_enqueue(alert_id)))
    run_worker(w.WorkerSettings, burst=True)  # sync entry: owns its event loop
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT run_id, disposition FROM {t('investigation_runs')}"
                            f" WHERE alert_id=? ORDER BY created_at DESC LIMIT 1", (alert_id,))
        assert row, "no audit row written by worker"
        print("worker wrote audit row:", row["run_id"], row["disposition"])
    finally:
        con.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "alert-demo-clean")
