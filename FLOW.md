# FLOW.md — how execution travels through OmniGuard AML

Notation: `file.py:function()` — arrows are calls, `→ DB` is a SQL round-trip.
All app code lives in `src/omniguard/`; `scripts/` are entry points.

## Module map

| Module | Owns | Calls into |
|---|---|---|
| `config.py` | `settings` (env: DATABASE_URL, REDIS_URL, LLM_PROVIDER, API_KEY, thresholds) | — |
| `db.py` | dialect switch, `connect()`, `init_db()`, `t()` table names, `dumps/loads` | `config.settings`, `db/schema_*.sql` |
| `injection.py` | `scan_transaction()`, `sandbox()` | — (pure) |
| `features.py` | `compute_features()` | — (pure) |
| `graph_features.py` | `compute_graph_features()` (NetworkX) | — (pure) |
| `ml.py` | `to_vector()`, `train()`, `load()`, `score()`, `explain()` | `config.settings`, `./models/*.pkl` |
| `policy_retrieval.py` | `retrieve()`, `pseudo_embed()` | `db.connect()`, `config.settings` |
| `prompts.py` | 4 templates, `prompt_version_hash()` | — (pure) |
| `llm.py` | `call_json(kind, payload)` — mock / NIM / Bedrock | `config.settings`, `prompts.prompt_version_hash()` |
| `verifier.py` | `verify_citations()`, `adjudicate()` | `config.settings` (thresholds) |
| `scenario_gen.py` | `generate_transactions()`, `sha256()`, `lock_expectations()`, `execute_control_48h_passthrough()`, `compare()` | — (pure) |
| `graphs_investigation.py` | Graph 1: `run_investigation()`, `review()`, `fetch_alert()`, `build_langgraph()` | features, graph_features, injection, ml, policy_retrieval, llm, verifier, db |
| `graphs_scenario.py` | Graph 2: `ingest()`, `run_scenariolab()`, `approve_and_execute()` | llm, scenario_gen, db |
| `queue.py` | `enqueue_investigation()`, `enqueue_scenario()`, `get_job()` | ARQ/Redis **or** in-process `_run_fallback()` → graphs_* |
| `api.py` | FastAPI routes, `require_key()` | queue, graphs_investigation.review, graphs_scenario, db |
| `worker.py` | ARQ `run_investigation_job`, `run_scenario_job` (docker) | graphs_* |

## Flow 1 — Investigate an alert (Graph 1, PRD §5)

```
Client
 └─POST /investigate/{alert_id} ── api.py:investigate()
    └─ queue.py:enqueue_investigation()
        ├─ REDIS_URL set → ARQ enqueue → worker.py:run_investigation_job()
        └─ else → _run_fallback() → graphs_investigation.py:run_investigation(alert_id)
            ├─ [N1] fetch_alert() → DB: alerts + accounts + transactions (+ high-risk set)
            ├─ [N1] features.py:compute_features() + graph_features.py:compute_graph_features()
            ├─ [N1] injection.py:scan_transaction() per tx → quarantined?
            │       injection.py:sandbox() wraps memos for LLM (HTML-escaped to prevent boundary breakout)
            ├─ [N2] ml.py:to_vector() → ml.score() → {supervised, anomaly, composite}
            │       ml.explain() → SHAP (or weight approx)
            ├─ [N3] policy_retrieval.py:retrieve(tags) → DB: policy_notes (top 3–5, current only)
            ├─ [N4a‖N4b] asyncio.gather → llm.py:call_json("investigator") ‖ call_json("challenger")
            │       (mock / NIM dual-chain / Bedrock InvokeModel; prompts.py:prompt_version_hash() logged)
            ├─ [N5] verifier.py:verify_citations(tx_ids ✓, policy currency ✓, numerics ✓)
            │       verifier.py:adjudicate(composite, exoneration, valid, quarantined)
            │       → RECOMMEND_ESCALATE | RECOMMEND_CLOSE | CONFLICT_HUMAN_REVIEW
            ├─ [N6] → DB: INSERT audit.investigation_runs (full evidence pack)
            └─ [N7] return {state: AWAITING_HUMAN_REVIEW} ── human gate pauses here

Client
 └─POST /investigate/{alert_id}/review ── api.py:investigate_review()
    └─ graphs_investigation.py:review(run_id, analyst, decision, rationale)
        ├─ [N8] → DB: read run.tx_watermark vs current latest tx_id
        ├─ stale? → DB: INSERT human_decisions(REQUEST_RERUN, stale_rerun=1) → {rerun_triggered}
        └─ fresh? → DB: INSERT human_decisions(decision, stale_rerun=0) → {finalized}
```

Key invariants on this path: LLM never does math (features precomputed);
memos travel XML-sandboxed, raw preserved; quarantine forces CONFLICT;
RECOMMEND_* never self-executes — gate always fires.

## Flow 2 — Stress-test a control (Graph 2 / ScenarioLab, PRD §6)

```
Client
 └─POST /scenario/ ── api.py:scenario_create()
    ├─ graphs_scenario.py:ingest(concern_text, submitted_by) → DB: INSERT scenario.risk_concerns
    └─ queue.py:enqueue_scenario() → graphs_scenario.py:run_scenariolab(concern_id)
        ├─ [ingest→author] llm.py:call_json("scenario_author") → Pydantic SPECS (params only)
        ├─ [generate] scenario_gen.py:generate_transactions(specs) → exact tx rows (code, no LLM)
        ├─ [lock] scenario_gen.py:sha256(specs) + lock_expectations() → expectations + expectation_hash
        ├─ [challenge] llm.py:call_json("scenario_challenger") → label-flip/leakage/consistency rubric
        ├─ → DB: INSERT scenario.scenario_sets(status=LOCKED) + scenario.expected_outcomes (sealed)
        └─ return {state: AWAITING_SIGNOFF}

Client
 └─POST /scenario/{id}/approve ── api.py:scenario_approve()
    └─ graphs_scenario.py:approve_and_execute(set_id)
        ├─ → DB: read set + sealed expectations; raise if status != LOCKED (idempotency guard);
        │       raise if sha256(expectations) != expectation_hash (tamper check, hard raise)
        ├─ [execute] scenario_gen.py:execute_control_48h_passthrough(txs) → {idx: ALERT|NO_ALERT}
        ├─ [report] scenario_gen.py:compare(expected, actual) → MATCH/MISS/OVER-ALERT + summary
        │       + COVERAGE_GAPS_DEFAULT ("what was NOT tested")
        ├─ → DB: INSERT scenario.control_runs (evidence_pack_hash) + UPDATE scenario_sets → EXECUTED
        └─ GET /scenario/{id}/results → DB: read latest control_runs row
```

## Flow 3 — Train (Phase 1)

```
scripts/train.py:main()
 ├─ db.py:connect() → DB: all transactions + high-risk accounts
 ├─ per account-window: features.py:compute_features() + graph_features.py:compute_graph_features()
 ├─ ml.py:to_vector() → X, label = any tx.is_laundering
 ├─ ml.py:train(X, y): LightGBM (or HistGB fallback) + IsolationForest
 │   → ./models/{supervised.pkl, isoforest.pkl, meta.json} + MLflow run
 └─ prints held-out P/R/F1 (GroupShuffleSplit by account — D20)
```

## Flow 4 — Evaluate (Phases 3–4)

```
scripts/eval50_v2.py → 50 distinct cases (eval3 set) → run_investigation per case
  → citation fidelity, numeric accuracy, injection 5/5, TP recall, TN ok → MLflow
scripts/baselines.py → flat-only vs flat+graph F1 (HistGB both arms)
  → single-LLM (investigator alone) vs dual-pipeline FPR → MLflow
```

## Cross-cutting paths

- **Config:** every module reads `config.py:settings` (env-overridable; "`./data/omniguard.db`",
  `LLM_PROVIDER=mock` defaults). `db.py:is_postgres()` + `t()` switch SQL dialect per call.
- **Auth:** `api.py:require_key()` (X-API-Key) gates every route except `/health`.
- **Seeding:** `scripts/seed.py` → `db.init_db()` (DDL) → INSERT accounts/transactions/
  `policy_notes` (with `policy_retrieval.pseudo_embed`) → demo alerts (+1 injection tx).
- **Tests:** `tests/test_phase{0..4}_*.py` drive the same functions above
  (unit → e2e → API TestClient); run order: `seed --reset → train → pytest`.
