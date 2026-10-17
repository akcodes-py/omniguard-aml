# DECISIONS.md — OmniGuard AML decision log

Every entry: context → decision → consequence. Statuses: ACCEPTED (implemented),
PROPOSED (upcoming, needs owner call), SUPERSEDED (replaced).

## Accepted (during build, 2026-10-15)

### D1. PKs are TEXT holding UUID strings — ACCEPTED
Context: PRD says UUID, starter `schema.sql` says TEXT.
Decision: TEXT columns, app generates `uuid4` strings; Postgres default
`gen_random_uuid()::text`. Canonical DDL: `db/schema_canonical.sql`.
Consequence: satisfies both docs; no migration needed either way.

### D2. Embedding dim frozen at 1024 (Titan v2), HNSW — ACCEPTED
Context: PRD assumed 1536 (OpenAI), starter used 1024 (Titan v2).
Decision: keep 1024 + HNSW per starter; recorded in `config.EMBEDDING_DIM`.
Consequence: PRD §4 text is stale on this point; update it if OpenAI
embeddings are ever adopted (requires re-embed + index rebuild).

### D3. Table name `policy.policy_notes`, field `body` — ACCEPTED
Context: PRD says `typology_notes.content`, starter says `policy_notes.body`.
Decision: starter naming wins (it ships the vector index).
Consequence: code + retrieval use `policy_notes.body`.

### D4. Transactions keep src/dst + add PRD-compat columns — ACCEPTED
Context: NetworkX needs directed edges; PRD lists direction/currency/
counterparty/alert_id fields the starter lacks.
Decision: superset schema (both). Memo stays RAW, never modified.
Consequence: graph + PRD queries both work; `is_laundering` is train/eval-only.

### D5. Audit stays append-only, TRUNCATE guards extended — ACCEPTED
Context: starter already stricter than PRD (TRUNCATE + `app_worker` role).
Decision: kept stricter version; extended to `scenario.control_runs` +
`expected_outcomes`; added missing `audit.model_promotions`.
Consequence: `seed --reset` cannot DELETE — it rebuilds the SQLite file
(this exact failure was caught by re-verification and fixed).

### D6. Added missing PRD tables — ACCEPTED
`core.graph_features`, `audit.model_promotions`, full `scenario.*`
(risk_concerns, scenario_sets, expected_outcomes, control_runs).
Consequence: DDL diff vs PRD §4 = 0 (table-level).

### D7. Local runtime fallbacks (no Docker on host) — ACCEPTED
SQLite + in-process queue + mock LLM + file-based MLflow locally;
canonical Postgres+pgvector / Redis+ARQ / Bedrock ships in
`docker-compose.yml` and is selected purely by env
(`DATABASE_URL`, `REDIS_URL`, `MOCK_LLM`).
Consequence: everything runs here with zero infra; deploy path untested.

### D8. LightGBM with HistGradientBoosting fallback — ACCEPTED
`ml.py` tries LightGBM, falls back to sklearn HistGB (logged as
`histgb_fallback` in `models/meta.json`). This host ran LightGBM 4.7.0.
Consequence: training never hard-fails on missing wheels.

### D9. Mock LLM is deterministic + schema-conformant — ACCEPTED
`llm.py` mock emits the same strict JSON schemas as Bedrock path; token
counts estimated; live path auto-falls-back to mock on any exception.
Consequence: CI/eval cost = 0; single-vs-dual baseline ties 0.0/0.0 on mock
(reported honestly — real differentiation needs Bedrock).

### D10. Single parallel LLM pass, boolean adjudicator — ACCEPTED (PRD §12)
No multi-round debate, no LLM judge, no LLM math, no Text-to-SQL,
no transaction vector search, never auto-close.
Consequence: enforced in `verifier.py`; eval asserts it.

### D11. SQLite needs single-event triggers — ACCEPTED
This SQLite build rejects `BEFORE UPDATE OR DELETE`; each guard table got
two single-event triggers. Postgres canonical keeps combined triggers.
Consequence: dev-only DDL quirk, documented in `db/schema_sqlite.sql`.

### D12. Eval reuses 3 seeded alerts (honest smoke eval) — SUPERSEDED (see D21: 50 distinct cases; PaySim later ingested — D20)
50 runs, not 50 distinct cases; no PaySim/IBM ingestion locally.
Consequence: metrics (citation 1.000 etc.) prove plumbing, not production
accuracy. Do not cite them as production claims.

### D13. ENV is the only config surface; JEV dropped — ACCEPTED (2026-10-16)
`config.py` carries the full surface (`LLM_PROVIDER`, NIM keys/models,
`STRICT_LLM`, rate limit); `.env.example` documents, `.env` ignored;
compose secrets fail fast (`:?`); grep gate `tests/test_phase1_env.py`.
JEV removed from scope per owner call — no JEV keys, no JEV client.

### D14. Phase 2: lean Docker on 8GB, PG18 coexistence — ACCEPTED (2026-10-16)
Host Postgres 18 owns port 5432 (service left running, untouched — stopping
needs admin). Container remapped to host **5433** (`DATABASE_URL`
`postgresql://omniguard@…:5433/omniguard`); compose `api/worker/mlflow`
moved to `full` profile — default `up` runs postgres+redis only (~350MB).
WSL2 capped at 3GB via `.wslconfig`. Redis must use `127.0.0.1` (Docker
proxy doesn't answer `::1`; redis-py has no Happy-Eyeballs fallback).
Central `db.run/fetchone/fetchall` (`?`→`%s` for psycopg); real booleans
for PG boolean cols; `Vector.to_list()` for pgvector reads; `text[]` gets
a real list. Verified: 16/16 on Postgres AND SQLite, ARQ burst→audit row,
HNSW top-4 identical to numpy fallback.

### D15. Phase 3: NIM dual-routing, mock-verified, key pending — SUPERSEDED (final routing: see D18 note + README Models line)
`llm.py` provider switch (`mock|nim|bedrock`); Investigator/Author →
`NIM_REASON_MODEL` (DeepSeek-V4.1-Flash; final = `nvidia/nemotron-3-super-120b-a12b`, see README Models), Challengers → `NIM_FAST_MODEL`
(Nemotron 3.5 Lightning); temperature 0, `response_format json_object`,
schema validation + repair retry, 429/backoff, per-provider pacing at
`RATE_LIMIT_PER_MIN`; real `usage` tokens into `token_cost`; STRICT raises,
non-strict degrades loudly. 21/21 pass (5 new NIM gates, no live key).
Live smoke (1 NIM investigation) pending owner adding `NIM_API_KEY` to `.env`.

### D16. Phase 3 remainder: 5-piece resilience, live findings — ACCEPTED (2026-10-16)
`llm.py`: (1) external idle timeout (pump thread + queue, 30s — in-loop
checks can't see keep-alive stalls); (2) 300s shared deadline; (3) smart
retries (retry timeout/429/5xx, fallback on 404, fatal on 401/400/403/422);
(4) fallback chain 552B→30B with `fallback:true` + real model_id in
`token_cost`; (5) cached fail-soft preflight. Plus: per-attempt timeout fit
inside remaining budget; idle-stall jumps straight to fallback (requeueing
loses queue position); per-attempt stderr logging.
Live truth: challenger on Lightning PROVEN (real usage: 996 tokens).
552B free tier currently serves keep-alives, never tokens — layer bounds it
(30s kills, fallback, degrade) instead of hanging. Pump shape proven
correct offline against a fake SSE server (openai v3 yields proper
ChatCompletionChunk; a matrix-probe pop() bug of mine briefly suggested
otherwise — probe bug, not SDK bug — caught and documented, not hidden).
28/28 pass (incl. idle-enforcement + idle-to-fallback offline tests).

### D18. Investigator promoted to Lightning, fallback Super-120B — SUPERSEDED (see note below: final = Super-120B primary, Lightning fallback)
552B dropped from the chain (free tier serves keep-alives, never tokens).
Primary investigator/author = Lightning-30B (proven live); fallback =
`nvidia/nemotron-3-super-120b-a12b` (proven invocable in 2s). Rejected
fallbacks (all 404/fast-fail on this free account): nemotron-70b,
mistral-7b, granite-8b, minitron-8b, gemma-3-4b. Live proof: Lightning
stalled → 30s idle kill → Super-120B answered, 672 real tokens,
`fallback:true` logged. Investigator+challenger share the Lightning brain
(limited independence loss — challenger is evidence-gated, not open
reasoning). 29/29 pass.
SUPERSEDED by D19-phase work: primary investigator/author is now Super-120B
(fast, proven), fallback Lightning-30B — the 552B is out entirely. The
rejected-candidates list and fallback-logging design above still stand.

### D20. Phase 5C: honest split + validated family shipping — ACCEPTED (2026-10-16)
GroupShuffleSplit by account (no leakage). Final ledger (n=338, account-first
PaySim): LightGBM flat_graph F1 0.545 vs flat_only 0.529 (graph +0.016 —
negligible); HistGB 0.457/0.529. Shipped = held-out argmax (LightGBM;
`ml.train(family=…)`), recorded in models/meta.json + MLflow. (An earlier
thin-sample round showed HistGB 0.833 — voided with the dataset that
produced it; ID-collision across loads silently measured stale windows,
fixed by per-generation namespaces ps2/eval3.)
Root-caused the 0.000s: LGBM with min_child_samples=20 starved on 142 train
rows, not a data bug.

### D19. Phase 5 live eval + README with real numbers — ACCEPTED (2026-10-16)
6-case NIM smoke on Postgres (Super-120B inv / Lightning challenger): citation
0.667 (both misses = title-cites caught to human review), injection 1/1,
dual escalate 0/6, single FP 3/3 (fair payloads), tokens 12.7k dual vs 9.9k
single, 1 challenger mock-degrade (logged). Returned `token_cost` was missing
from run_investigation (audit-only) — now forwarded. Scorer outputs 0.2913 for
every alert (toy-data ML failure, stated in README — not a pipeline verdict).
Single-arm lobotomized-payload history voided; fair comparison only from this
run. README measured-results rewritten with live table + caveat + phases.

### D17. Phase 4: one-page React UI — ACCEPTED (2026-10-16)
`ui/` (Vite + React 19, plain CSS, no framework): key bar (memory only),
Health, Investigate (submit → poll → disposition card → review form),
ScenarioLab (concern → poll → approve → results). `VITE_API_URL`
overridable, default `http://localhost:8000`; dev CORS allow-listed in
`api.py`. Found + fixed latent bug: status response lacked `set_id`, so
approve-by-concern-id 500'd — covered by new scenario end-to-end test.
Verified: `npm run build` clean, API+preview boot together and serve,
29/29 pass. Manual browser click-through left to owner (no browser here).

### D21. All phases complete — ACCEPTED (2026-10-16)
50 distinct cases (PaySim account-first + synth, eval3 set): TP 4 esc/11
conflict/0 close, TN 8 close, injection 5/5 quarantined, citation 1.000.
Fraud is never auto-cleared; clean mostly closes. Challenger exoneration on
random KYC is noise (stated) — real KYC feed required for that signal to mean
anything. Edges: CI workflow, DEMO.md script, clean-clone compose verified
(fail-fast messages + config), UI click-through ready.
32 tests green on SQLite; verified complete.

### D22. MLflow file store re-enabled + train metrics split — ACCEPTED (2026-10-17)
Context: verification pass found MLflow 3.x raises on the `./mlruns` file
store by default, and `train.py` logged a string (`shipped_family`) via
`log_metrics` — both swallowed by `except: pass`, so zero experiment data
existed (`mlruns/` absent) while docs claimed tracking. Found during
codebase verification (the behavior would silently recur with any mlflow>=3).
Decision: `config.py` sets `MLFLOW_ALLOW_FILE_STORE=true` via `setdefault`
(real env still wins); `train.py` logs numeric metrics only + `shipped_family`
as a param, and warns to stderr instead of silently skipping.
Consequence: `mlruns/` now holds real runs (train_split: 14 metrics matching
README table P/R/F1; train: pos_rate). File store is MLflow "maintenance
mode" — v2 should migrate to `sqlite:///mlflow.db` or the compose server.

## Proposed (v2 Roadmap)

### P1. Dedicated Production LLM Endpoints — PROPOSED
Call: Set `LLM_PROVIDER=nim` (dedicated NIM) or `LLM_PROVIDER=bedrock` (AWS
Bedrock Claude 3.5 Sonnet) for high-volume production throughput beyond
free-tier rate limits.

### P2. Canonical Deploy Verification — PROPOSED
Call: Run full multi-container stack (api, worker, postgres+pgvector, redis, mlflow)
in Docker Desktop environment with live ARQ job queues and persistent pgvector indices.

### P3. Real-Time Streaming Architecture — PROPOSED
Call: Transition from windowed batch processing to Apache Kafka / Apache Flink
streaming ingestion for sub-second anomaly detection.
