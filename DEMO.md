# DEMO.md — 10-minute recorded walkthrough script

## Setup (before recording)
1. `docker compose up -d postgres redis` (+ `docker compose --profile full up -d mlflow` if RAM allows)
2. Copy `.env.example` to `.env`, fill `POSTGRES_PASSWORD`, `API_KEY`, `NIM_API_KEY`
3. `python scripts/seed.py --reset && python scripts/train.py && python -m pytest -q`
4. Terminal A (repo root): `$env:PYTHONPATH='src'; $env:DATABASE_URL='postgresql://omniguard:<pw>@localhost:5433/omniguard'; python -m uvicorn omniguard.api:app --port 8000` (root CWD so `.env` loads; PG URL so eval + PaySim data is visible — SQLite only has toy alerts)
5. Terminal B: `cd ui && npm run dev` → http://localhost:5173

## Part 1 — Investigate a live alert (4 min)
1. Paste API key. Show `/health` → `{llm: nim}`.
2. Investigate `eval-tp-00` → poll → disposition card: composite score,
   SHAP top features, verifier result, cited tx/policy ids.
3. Submit review as `analyst-1` → ESCALATE with a note → `finalized`.
4. Show the audit row: `SELECT disposition, token_cost FROM audit.investigation_runs
   ORDER BY created_at DESC LIMIT 1;` — point at model_id, attempts,
   latency_ms, fallback flag.

## Part 2 — Kill the giant, watch the fallback (2 min)
1. Investigate `eval-tn-03` while narrating: Super-120B stalls on the free
   queue → 30s idle kill → Lightning answers → `fallback:true` in the row.
2. Show an injection case (`eval-inj-0`): quarantined memo, forced
   CONFLICT_HUMAN_REVIEW, raw memo preserved.

## Part 3 — ScenarioLab (3 min)
1. Concern: "smurfing via micro-deposits under reporting threshold" → Generate.
2. Show 4 specs + SHA-256 lock + challenger findings → Approve.
3. Results table: MATCH/MISS/OVER-ALERT, coverage gaps ("what was NOT tested"),
   evidence_pack_hash.

## Part 4 — Numbers (1 min)
Show README measured-results: live 6-case table, 50-case mock table,
held-out ML table. Read the caveat paragraph aloud — honesty is the demo.
