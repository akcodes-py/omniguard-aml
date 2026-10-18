# OmniGuard AML — Session Tracking Log

**Date:** 2026-10-17 (Asia/Kolkata)
**Repo:** `omniguard-aml` · branch `main`
**Session covered:** everything done in the current window — docs truth pass → IBM HI-Small benchmark experiment → UI redesign (workbench) + real API-key verification → hardening pass (Tier 1 + selected Tier 2).

---

## 0. Session summary

| # | Workstream | Status | Commit(s) |
|---|-----------|--------|-----------|
| A | Docs truth pass (README / DECISIONS / FLOW / V1 / llm.py) | ✅ done | `27784a1` |
| B | IBM HI-Small dataset experiment (isolated DB + MLflow) | ✅ done | `1c2db60` |
| C | UI redesign → workbench + `GET /auth/check` | ✅ code done · ⏳ browser click-through pending | `c876e94` (swept in) → `6efb8fa` (final) |
| D | Hardening pass (Tier 1 + selected Tier 2) | ✅ done, 35 tests green | (uncommitted → this commit) |
| — | README full revamp (badges, mermaid, benchmarks) | ✅ done (parallel commit) | `bc424a0` |
| — | V2 documentation (PDF) | ✅ added (parallel commit) | `e666cb4` |

---

## 1. Docs truth pass — commit `27784a1`

Made every doc claim match shipped reality:

- **README** — Models line sourced from `config.py`; smoke table relabeled "plumbing check only"; three mock caveats added; "Reads:" wording notes **4 of 15 TPs escalated** (not all); deploy wording → *"Postgres and Redis verified live; full api/worker/mlflow stack not run end-to-end (D7, D14, P2)"*; Bedrock → *"path written, not tested live"*; graph-lift noise note; FLOW.md + DECISIONS.md links; "Built in about two days".
- **DECISIONS.md** — D12 / D15 / D18 marked **SUPERSEDED**; encoding repaired (3× `Â§`→`§`, 2× `â€¦`→`…`); P1 `MOCK_LLM=false` → `LLM_PROVIDER=nim|bedrock`.
- **docs/V1.md** — why-cell rewritten ("Bedrock lacks DeepSeek" removed).
- **FLOW.md** — stale references fixed.
- **llm.py** — comments updated to match reality.

---

## 2. IBM HI-Small experiment — commit `1c2db60`

Run **fully isolated** from the demo environment (no pollution of shipped models or demo DB):

- **Data**: Kaggle IBM AML `HI-Small` — 454 MiB downloaded.
- **Loader**: `scripts/load_ibm.py`. Key fix: bank/account IDs are zero-padded / hex **strings** (`010`, `8000EBD30`) — read as object dtype, never int.
- **Ingestion**: `omniguard_ibm` PostgreSQL DB — **8,941 accounts, 53,785 transactions, 601 laundering**, 2022-09-01 → 2022-09-18, ~128 s.
- **Training**: isolated MLflow store `./mlruns_ibm`.
  - Windows **n = 4,982** (pos_rate 0.089); held-out **n = 1,246**.
  - LightGBM: fraud-graph P/R/F1 = **0.630 / 0.408 / 0.495**; fraud-only = 0.683 / 0.344 / 0.457.
  - HistGB: fraud-graph = 0.619 / 0.416 / **0.498** (best argmax F1); fraud-only = 0.627 / 0.336 / 0.438.
  - Held-out run id: `4014adf5efcb4ea681ebc969789919b6`.
- **Safety**: `models/` backed up → **restored byte-for-byte** (hashes re-verified: isoforest `C97DE09C…`, meta.json `B4A69669…`, supervised `EE0E9BC6…`). Repo `models/` = the shipped PaySim LightGBM, n=338.
- **Repo changes**: `.gitignore` gains `mlruns_ibm/`; README ML table restructured to a **Dataset column** (PaySim n=338 + IBM HI-Small n=4,982, all 4 model combos each).
- **Honest caveats recorded**: account-first sample (400 laundering-touched + 1,500 clean, seed 42); multi-currency amounts summed as-is; HI-Small spans only 18 days.
- **Note**: the train job printed "exit code 1" — benign PowerShell `NativeCommandError` from an MLflow stderr banner; the run completed and is verifiable in the `mlruns_ibm` metric files.

---

## 3. UI redesign + `/auth/check` — commits `c876e94` (user-side sweep) + `6efb8fa` (final)

### 3.1 Files changed

| File | Change |
|---|---|
| `ui/package.json` (+lock) | + `tailwindcss`, `@tailwindcss/vite` (dev) |
| `ui/vite.config.js` | Tailwind v4 plugin registered |
| `ui/src/index.css` *(new)* | `@import "tailwindcss";` + `color-scheme: dark` |
| `ui/src/main.jsx` | imports `index.css`; crash boundary restyled to slate (`#0B0F17`) |
| `ui/src/api.js` | `getLastCallMs()` real latency metric; key memory-only note kept |
| `ui/src/App.jsx` | **full rewrite** (~460 lines) — workbench layout, all flows preserved |
| `src/omniguard/api.py` | new authed `GET /auth/check` |
| `tests/test_phase4_api.py` | assertions: `/auth/check` → 401 no key · 200 with key |
| `README.md` | Web Interface bullets aligned with shipped UI (final commit) |

### 3.2 Design language (as proposed, slate workbench)

- Palette `#0B0F17` bg / `#111827` cards; indigo primary; semantic colors: emerald = connected/cleared, amber = pending, crimson = risk.
- Monospace for IDs, amounts, hashes, latency.
- **Header**: brand + `V1` chip, tab switcher with **session record counts**, API status badge.
- **Status badge**: amber "API Key Required" → green "Engine Connected" / red "Key Not Verified"; click opens the key drawer; editing the key resets verification; verify = real `GET /auth/check` (+ `/health` details line); drawer note: *"key held in memory only — never persisted or logged"*.
- **Split workbench**: left = dispatch (form + presets), right = evidence ledger (table + detail + raw evidence + footer stamp).

### 3.3 Flows preserved (verbatim behaviors)

- **Investigation**: `POST /investigate/{id}` → poll `/status` every 1.5 s × 20 → timeout error text kept. Ledger columns: composite ML score, disposition pill, citation count, tokens, review status.
- **Analyst review**: `POST /investigate/{alert}/review` with `{run_id, analyst_id, decision, notes}` — decisions **ESCALATE / CLOSE / REQUEST_RERUN / RETURN_FOR_RERUN**.
- **Scenario**: `POST /scenario/` → poll until `scenarios_generated` → `AWAITING_SIGNOFF` row → **human Approve gate** → `POST /scenario/{set_id}/approve` → control results (expected/actual/verdict pills), "What was NOT tested" gaps, evidence-pack hash, raw evidence.
- `J()` dual-shape parsing (PG jsonb objects vs SQLite strings) kept everywhere.
- Session-scoped counts; footer shows real **last API-call latency** + "APPEND-ONLY AUDIT TRAIL: ENABLED".

### 3.4 Honesty edits baked into the UI

- `V1` chip (not "Core v2.4"); **"Alert Triage"** (not "SAR / Triage"); "APPEND-ONLY AUDIT TRAIL" (not FINCEN/FATF claims).
- Presets are **real alert IDs only**: `eval3-tp-00` (default), `eval3-inj-00`, `eval3-lik-00`, `alert-demo-rapid` — invented chips would 404.
- Scenario button says **"Generate Scenarios"** (not "Execute") with helper text: execution runs only after approval.
- Final commit `6efb8fa` also **renders challenger findings** in the scenario ledger (adversarial review per scenario: verdict / leakage / consistency), and README bullets were trimmed of claims the UI doesn't have (SHAP charts, per-tx citation badges, Pydantic-spec inspection).

---

## 4. Hardening pass (Tier 1 + selected Tier 2) — D23a–j

Code review found security/robustness gaps the test suite didn't catch. None change happy-path behavior; all 35 tests green.

| ID | Change | File | Why |
|---|---|---|---|
| D23a | Injection sandbox HTML-escapes `<`, `>`, `&` before wrapping | `injection.py` | Prevents a memo containing `</untrusted_…>` from closing the boundary early |
| D23b | Tamper check is an explicit `raise ValueError`, not `assert` | `graphs_scenario.py` | Survives `python -O` / `PYTHONOPTIMIZE=1`, which strips `assert` |
| D23c | Scenario approve guarded: missing set/outcomes → `KeyError`; non-`LOCKED` state → `ValueError` | `graphs_scenario.py` | Idempotency — no duplicate control run / double hash |
| D23d | MLflow failures logged (`_log.warning`) instead of silent `pass` | `ml.py` | Consistent with D22 (train.py) |
| D23e | 5 bare `except Exception: pass` → `except … as exc` + `_log.debug` | `graph_features.py` | Failures visible while still degrading to zeros |
| D23f | Empty citation sets no longer vacuously valid (`tx_ok` requires ≥1 cite when window non-empty) | `verifier.py` | A citation-less investigation must not be marked valid |
| D23g | High-risk filter `IS TRUE` → bare column (dialect-safe) | `graphs_investigation.py` | Works on both Postgres and SQLite |
| D23h | Pydantic `ReviewBody` / `ScenarioBody` replace untyped `dict` | `api.py` | Malformed bodies → 422, not 500 `KeyError`; `concern_text` min_length=1 |
| D23i | Resilience logging via stdlib `logging` (8 `print` → `_log`) | `llm.py` | Enables log-level control; no behavior change |
| D23j | Deleted stale orphan `__pycache__/hf_data.cpython-314.pyc` | `src/omniguard/__pycache__/` | No source existed |

**Tests added (3):** `test_injection_sandbox_escapes_closing_tag`, `test_verifier_empty_citations_not_vacuously_valid`, `test_approve_requires_locked_state`. Test count: 32 → **35**.

---

## 5. Verification evidence

| Check | Result |
|---|---|
| `npm run build` (ui) | ✓ built (≈246 kB JS / 24 kB CSS) |
| `python -m pytest -q` | **35 passed** (SQLite, ~31 s) |
| `curl /health` | 200 |
| `curl /auth/check` without key | **401** |
| `curl /auth/check` with `X-API-Key` | **200** `{"status":"ok","auth":"valid"}` |
| Dev server `/src/App.jsx` | 200 — serves new UI |
| Dev server `/src/index.css` | compiled Tailwind |

---

## 6. Current environment state

| Component | Status |
|---|---|
| API `:8000` | **up** (restarted to load `/auth/check`; PG `postgresql://omniguard:***@localhost:5433/omniguard`) |
| UI `:5173` | **up** (vite dev, background) |
| Docker | `omniguard-aml-postgres-1` — Up (healthy) |
| Databases | `omniguard` (demo/eval) · `omniguard_ibm` (IBM experiment, isolated) |
| MLflow | `./mlruns` (PaySim) · `./mlruns_ibm` (IBM, gitignored) |
| API key | in `.env` → `API_KEY` — value intentionally **not** written in this file |

---

## 7. Pending / next steps

1. **Browser click-through (owner: user)** — the last unverified step:
   1. Open http://localhost:5173 → badge amber → paste key from `.env` → **Verify** → green + service line.
   2. Investigations → `eval3-tp-00` → Launch → row appears → pick decision (e.g. ESCALATE) + notes → Submit.
   3. Scenario Runs → Generate Scenarios (default concern) → `AWAITING_SIGNOFF` + Challenger findings → **Approve** → Control results + "What was NOT tested" + evidence hash.
   4. Footer latency updates; tab counts grow per session.
2. After confirmation: add a short "click-through verified" honesty note to README (the old *"Manual click-through pending"* line was removed by the README revamp `bc424a0` — nothing left to delete).
3. Optional, on request: D23 entry already added (D23a–j); Tier 3/4 items from the review remain open (unit tests for `ml`/`graph_features`/`policy_retrieval`/`queue`, UI tests, logging migration, roadmap features).

---

## 8. Notes & invariants kept

- Parallel commit stream (user-side) added `bc424a0` (README revamp), `c876e94` (swept in the UI work + HI-Small pipeline benchmark table), `e666cb4` (V2 documentation PDF); `App.jsx` was verified intact inside `c876e94`.
- **Key never persisted** (memory-only, never localStorage / logs) — documented invariant in `api.js` and the UI drawer.
- **No fake UI elements**: key verification, counts, and latency are all real calls.
- **Docs match reality**: overclaims removed; remaining caveats kept.
- **Tier 4 (product roadmap)** from `docs/V2.md` + P1–P3 remains unstarted by design.
