"""ARQ worker entry (docker) — mirrors the fallback jobs in queue.py.

Run: python -m omniguard.worker
"""
from __future__ import annotations


async def run_investigation_job(ctx, alert_id: str) -> dict:
    from . import graphs_investigation as gi

    return await gi.run_investigation(alert_id)


async def run_scenario_job(ctx, concern_id: str) -> dict:
    from . import graphs_scenario as gs

    return gs.run_scenariolab(concern_id)


class WorkerSettings:
    functions = [run_investigation_job, run_scenario_job]


if __name__ == "__main__":
    import asyncio

    from .config import settings

    async def _main() -> None:
        if not settings.REDIS_URL:
            print("REDIS_URL unset — nothing to consume (API uses in-process fallback).")
            return
        from arq import run_worker

        await run_worker(WorkerSettings)

    asyncio.run(_main())
