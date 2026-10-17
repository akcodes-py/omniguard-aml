# OmniGuard AML

Dual-pipeline financial-crime compliance platform (per `omniguard_product_plan.md`):
**upstream ScenarioLab** (control stress-testing with SHA-256-locked expected outcomes)
+ **downstream investigation** (ML-scored, LLM-investigated, citation-verified alert triage).

**Models:** NVIDIA NIM — `nvidia/nemotron-3-super-120b-a12b` (investigator + scenario author; primary) · `nvidia/nemotron-3.5-lightning-30b-a3b` (challengers + fallback) · local default `LLM_PROVIDER=mock`.

Built in about two days (2026-10-15 → 17) — see [FLOW.md](FLOW.md) for the execution flow and [DECISIONS.md](DECISIONS.md) for the decision log.

## Quickstart (local, no Docker)

```powershell
cd omniguard-aml
pip install -r requirements.txt
python scripts/seed.py --reset
python scripts/train.py
python -m pytest -q
python scripts/eval50_v2.py --prefix eval3   # needs Postgres up (docker compose up -d postgres redis)
$env:PYTHONPATH='src'; uvicorn omniguard.api:app --port 8000  # repo root so .env loads
```

Docker compose ships 5 services (`docker-compose.yml`: api, worker, postgres+pgvector,
redis, mlflow). Postgres and Redis were verified live; the full api/worker/mlflow
stack has not been run end-to-end on this machine (D7, D14, P2). Local defaults
use SQLite + in-process queue + mock LLM so everything runs here.

## Architecture

```
investigate -> fetch/sanitize -> ML score -> policy retrieval -+-> Investigator -+-> verify/adjudicate -> audit -> HUMAN GATE -> finalize
                                                             +-> Challenger  -+
scenario    -> ingest -> author -> generate (code) -> lock SHA-256 -> challenge -> SIGNOFF -> execute control -> report
```

## UI

```powershell
cd ui; npm install; npm run dev      # http://localhost:5173
$env:PYTHONPATH='src'; $env:DATABASE_URL='postgresql://omniguard:<pw>@localhost:5433/omniguard'; python -m uvicorn omniguard.api:app --port 8000   # repo root (loads .env); PG URL for eval/PaySim data
```
One page: API-key bar, Health, Investigate (submit → poll → review),
ScenarioLab (concern → approve → results). Manual click-through pending
(audit honesty: serving + API flows verified, browser clicks are yours).

## Measured results

### Held-out ML (group split by account — no leakage)

| Dataset | Model | Features | P | R | F1 |
|---|---|---|---|---|---|
| PaySim, n=338 | LightGBM (shipped — held-out argmax) | flat + graph | 0.643 | 0.474 | **0.545** |
| PaySim, n=338 | LightGBM | flat only | 0.600 | 0.474 | 0.529 |
| PaySim, n=338 | HistGB | flat + graph | 0.500 | 0.421 | 0.457 |
| PaySim, n=338 | HistGB | flat only | 0.600 | 0.474 | 0.529 |
| IBM HI-Small, n=4,982 | LightGBM | flat + graph | 0.630 | 0.408 | 0.495 |
| IBM HI-Small, n=4,982 | LightGBM | flat only | 0.683 | 0.344 | 0.457 |
| IBM HI-Small, n=4,982 | HistGB (held-out argmax for that run) | flat + graph | 0.619 | 0.416 | **0.498** |
| IBM HI-Small, n=4,982 | HistGB | flat only | 0.627 | 0.336 | 0.438 |

PaySim block 2026-10-16 (470 MB ledger, account-first). IBM block 2026-10-17:
Kaggle HI-Small sample, account-first (400 laundering-touched + 1,500 clean
accounts, seed 42, `scripts/load_ibm.py`), held-out n=1,246; multi-currency
amounts kept as-is. Graph lift (PaySim): +0.016 for LightGBM, −0.07 for HistGB — test set is small (held-out n=85, 19 positives; recall 0.474 ≈ 9 of 19),
so differences of this size are within noise. Shipped `models/` stays the PaySim
held-out argmax (see `models/meta.json` + MLflow); the IBM run was isolated
(`omniguard_ibm` DB, `mlruns_ibm`) and did not replace it. Small data, modest
scores, no leakage. No production claim.

### 50 distinct cases, mock LLM (2026-10-16, Postgres, PaySim + synth)

| Cat | n | Escalate | Close | Conflict | Citation | Quarantine |
|---|---|---|---|---|---|---|
| TP | 15 | 4 | 0 | 11 | 1.000 | — |
| TN | 10 | 0 | 8 | 2 | 1.000 | — |
| Lookalike | 10 | 0 | 6 | 4 | 1.000 | 0.100 |
| Boundary | 10 | 0 | 7 | 3 | 1.000 | — |
| Injection | 5 | 0 | 0 | 5 | 1.000 | 1.000 |

- Citation 1.000 holds by construction, because the mock emits valid IDs.
- Injection quarantine was tested on 5 hand-written memos.
- Challenger exoneration uses random KYC, so it carries no signal (D21).

Reads: only 4 of 15 true positives were escalated — the other 11 went to
human review, so fraud is never auto-closed; clean is mostly closed;
injection always quarantined + human-reviewed. The 1 quarantined lookalike
is a regex FP on a benign memo (logged, tolerated — quarantine only forces
review). Overall citation 1.000.

### Live NIM smoke (2026-10-16, Postgres, Super-120B + Lightning-30B, n=6)

Citation 0.667 (2 title-instead-of-id cites → human review, as designed),
injection 1/1, tokens dual 12.7k vs single 9.9k, one challenger mock-degrade
under congestion (logged). Escalation counts: plumbing check only, not a
quality comparison (toy scorer returned a constant 0.2913; the single/dual
arms had different n — D19).

### The honest caveat (read before quoting anything)
Small data (338 windows), modest scorer (F1 0.545), free-tier congestion.
The pipeline logic is verified (fraud never auto-clears, citations enforced,
injection quarantined); the scorer and the NIM free tier are the limits,
both stated with numbers above. Bigger ledger + paid inference change the
numbers, not the architecture.

## What's next (v2 roadmap)

- **Streaming Ingestion:** Real-time event streaming via Kafka / Apache Flink for continuous sub-second transaction window aggregation.
- **Graph Neural Networks:** Neo4j graph persistence and PyG/DGL GNN models to detect multi-hop layering and complex money-muling rings beyond immediate counterparty 1-hop lookups.
- **Adverse Media & OSINT:** External web/news screening integrations for real-time customer intelligence and sanction list corroboration.
- **Multi-Tenant Compliance:** Role-based access control (RBAC), multi-tenant partition isolation, and regulatory SAR generation (FinCEN XML export).

## Limitations (stated plainly)

- **Ledger Size & ML Scorer:** Scorer trained on 338 account windows (PaySim group split) achieving held-out F1 of 0.545. Validated against data leakage, but serves as a pipeline prototype rather than a production enterprise model.
- **Inference Free-Tier Congestion:** Free-tier NVIDIA NIM endpoints suffer intermittent latency and queue throttling; graceful degrade and fallback to fast models (Lightning-30B / deterministic mock) are implemented and logged.
- **Bedrock:** alternate provider path is written (`LLM_PROVIDER=bedrock` in `llm.py`) but not tested live; NIM + mock are the exercised paths.
- **Scope Boundaries:** No direct external wire network feeds, Kafka infrastructure, or GNNs are included in this v1 milestone (see v2 roadmap).

## Refusals enforced

No auto-close (human gate always fires), no Text-to-SQL (parameterized only),
no multi-round LLM debate (single parallel pass), no LLM judge/math
(boolean adjudicator + precomputed features), no transaction vector search
(exact SQL only; pgvector for policies/scenarios only).
