# OmniGuard AML

Dual-pipeline financial-crime compliance platform (per `omniguard_product_plan.md`):
**upstream ScenarioLab** (control stress-testing with SHA-256-locked expected outcomes)
+ **downstream investigation** (ML-scored, LLM-investigated, citation-verified alert triage).

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

Docker compose (`docker-compose.yml`, 5 services: api, worker, postgres+pgvector,
redis, mlflow) is the canonical deployment; local defaults use SQLite +
in-process queue + mock LLM so everything runs on this machine.

## Architecture

```
investigate -> fetch/sanitize -> ML score -> policy retrieval -+-> Investigator -+-> verify/adjudicate -> audit -> HUMAN GATE -> finalize
                                                             +-> Challenger  -+
scenario    -> ingest -> author -> generate (code) -> lock SHA-256 -> challenge -> SIGNOFF -> execute control -> report
```

## UI

```powershell
cd ui; npm install; npm run dev      # http://localhost:5173
$env:PYTHONPATH='src'; python -m uvicorn omniguard.api:app --port 8000   # from repo root (loads .env)
```
One page: API-key bar, Health, Investigate (submit → poll → review),
ScenarioLab (concern → approve → results). Manual click-through pending
(audit honesty: serving + API flows verified, browser clicks are yours).

## Measured results

### Held-out ML (2026-10-16, PaySim account-first ledger, n=338 windows, group split by account)

| Model | Features | P | R | F1 |
|---|---|---|---|---|
| LightGBM (shipped — held-out argmax) | flat + graph | 0.643 | 0.474 | **0.545** |
| LightGBM | flat only | 0.600 | 0.474 | 0.529 |
| HistGB | flat + graph | 0.500 | 0.421 | 0.457 |
| HistGB | flat only | 0.600 | 0.474 | 0.529 |

Graph lift: +0.016 for LightGBM, −0.07 for HistGB — negligible at this N.
Shipped model = held-out argmax, recorded in `models/meta.json` + MLflow.
Small data, modest scores, no leakage (split by account). No production claim.

### 50 distinct cases, mock LLM (2026-10-16, Postgres, PaySim + synth)

| Cat | n | Escalate | Close | Conflict | Citation | Quarantine |
|---|---|---|---|---|---|---|
| TP | 15 | 4 | 0 | 11 | 1.000 | — |
| TN | 10 | 0 | 8 | 2 | 1.000 | — |
| Lookalike | 10 | 0 | 6 | 4 | 1.000 | 0.100 |
| Boundary | 10 | 0 | 7 | 3 | 1.000 | — |
| Injection | 5 | 0 | 0 | 5 | 1.000 | 1.000 |

Reads: fraud is never closed (4 escalated, 11 human-reviewed); clean is
mostly closed; injection always quarantined + human-reviewed. The 1
quarantined lookalike is a regex FP on a benign memo (logged, tolerated —
quarantine only forces review). Overall citation 1.000.

### Live NIM smoke (2026-10-16, Postgres, Super-120B + Lightning-30B, n=6)

Citation 0.667 (2 title-instead-of-id cites → human review, as designed),
injection 1/1, dual escalate 0/6 (toy scorer era — superseded by the tables
above), single-LLM FP 3/3 on clean, tokens dual 12.7k vs single 9.9k.
One challenger mock-degrade under congestion (logged).

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
- **Scope Boundaries:** No direct external wire network feeds, Kafka infrastructure, or GNNs are included in this v1 milestone (see v2 roadmap).

## Refusals enforced

No auto-close (human gate always fires), no Text-to-SQL (parameterized only),
no multi-round LLM debate (single parallel pass), no LLM judge/math
(boolean adjudicator + precomputed features), no transaction vector search
(exact SQL only; pgvector for policies/scenarios only).
