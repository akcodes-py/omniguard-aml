# Model Card — OmniGuard AML Investigation Engine

**Version:** 1.0 · **Status:** prototype compliance pipeline · **Owner:** OmniGuard security & governance

## 1. Model identity and intended use

| Item | Value |
|---|---|
| Supervised model | LightGBM binary classifier (`models/supervised.pkl`), 19 features, trained on 338 account windows from the seeded synthetic ledger; sklearn `HistGradientBoostingClassifier` is the documented offline fallback |
| Anomaly model | `IsolationForest` (`models/isoforest.pkl`), `contamination="auto"`, `random_state=42` |
| Composite score | `0.7 × supervised_probability + 0.3 × anomaly_score` (weights in `settings`) |
| Decision thresholds | `composite >= 0.70` → `RECOMMEND_ESCALATE`; `composite < 0.30` **and** grounded exoneration → `RECOMMEND_CLOSE`; everything else → `CONFLICT_HUMAN_REVIEW` |
| Intended use | Decision-support for AML alert triage: rank and explain risk, assemble grounded evidence, and route cases to a human compliance analyst |
| Out of scope | Autonomous closing of alerts, SAR filing, customer onboarding decisions, sanctions screening, any production use without a human reviewer and institution-specific validation |

The model reads **19 deterministic features** computed in Python/SQL (`features.py`, `graph_features.py`): transaction counts and amounts, pass-through ratio, 24h velocity, night ratio, structuring flags, new-counterparty ratio, high-risk jurisdiction touch, and NetworkX graph metrics (PageRank, betweenness, in/out degree, cycle, community, shortest path). It never receives raw customer text.

---

## 2. Explainability

**(a) LightGBM SHAP attributions + verified RAG citations.** `ml.explain()` runs `shap.TreeExplainer` on the shipped classifier and returns the top-5 signed feature attributions for each scored alert. They are persisted with the case in `audit.investigation_runs.shap_explanation` and shown in the analyst review view. When SHAP is unavailable, a documented gain × deviation approximation is used and the result is still surfaced — never silently omitted.

Model reasoning is paired with **grounded policy citations**: `policy_retrieval.retrieve()` searches only versioned policy notes (`effective_to IS NULL`) in pgvector (or the deterministic local pseudo-embedding). The Investigator must cite exact `policy_id` + `version` pairs; `verifier.verify_citations()` checks:

- every cited `tx_id` exists in the fetched transaction window;
- every cited policy ID/version exists and is currently effective (titles are explicitly not accepted as citations);
- every numeric claim matches the SQL-computed feature within `$0.01`.

Any failure sets `citations_valid = false`, logs an `LLM07:2026` security event, and forces `CONFLICT_HUMAN_REVIEW`. Retrieved chunks are scanned for injected instructions before use; poisoned chunks are dropped and logged rather than shown to the model.

---

## 3. Human-in-the-loop (HITL) escalation rules

**(b)** Every adjudication output is a *recommendation*. `verifier.hitl_required()` is true for `RECOMMEND_ESCALATE`, `RECOMMEND_CLOSE`, and `CONFLICT_HUMAN_REVIEW`; the LangGraph `interrupt_before=["human_gate"]` pauses the graph before finalization. Only `graphs_investigation.review()` — called by an authenticated analyst via `POST /investigate/{alert_id}/review` — writes to `audit.human_decisions`.

| Trigger | System action | Analyst sees |
|---|---|---|
| Transaction memo injection detected | Quarantine raw memo (preserved as evidence), XML-sandbox for LLM input, force `CONFLICT_HUMAN_REVIEW` | Injection scan with flagged field names |
| Retrieved policy chunk contains injected instructions | Drop chunk, force `CONFLICT_HUMAN_REVIEW` | RAG quarantine metadata (policy ID, flagged fields) |
| Any citation or numeric claim fails verification | Reject output, force human triage | Verifier result with `tx_ok` / `pol_ok` / `math_ok` |
| Challenger claims exoneration without a real, non-empty KYC field | Ignore claim (`verify_exoneration`) | Grounded exoneration flag in verifier result |
| High composite score (`>=0.70`) without grounded exoneration | `RECOMMEND_ESCALATE` — never auto-close | SHAP drivers + policy citations |
| Low composite (`<0.30`) **and** grounded exoneration | `RECOMMEND_CLOSE` — still requires signoff | Same evidence pack |
| Stale watermark (new transactions since the run) | Convert any decision to `REQUEST_RERUN` | Staleness notice and latest transaction ID |

Every HITL event is written to the security event log with `action_taken` = `HITL_ESCALATION`, `HITL_RERUN_TRIGGERED`, `HITL_ESCALATE`, `HITL_CLOSE`, etc. A prompt injection cannot override Python state: `adjudicate()` is deterministic and ignores narrative text, claimed dispositions, and injected booleans.

---

## 4. Bias awareness — slice-level false-positive parity

**(c)** The simulated dataset (`scripts/seed.py`, seed 42) contains 40 accounts, 300 benign transactions and 40 laundering transactions with `is_laundering` ground truth. `scripts/bias_audit.py` builds one case per account, scores it through the same feature → vector → composite path as the investigation graph, and computes false-positive rate (FPR = FP / (FP + TN)) per slice using `predicted_alert = composite >= 0.70`. Parity criterion: `|slice FPR − overall FPR| <= 0.10`.

Reproduce with:

```powershell
python scripts/bias_audit.py --out data/bias_audit.json
```

Observed results (40 cases, 19 negatives/21 positives):

| Slice | n (negatives) | FPR | Gap vs overall | Parity |
|---|---:|---:|---:|:---:|
| **Overall** | 40 (19) | 0.000 | — | — |
| Amount tier: low (<1k) | 3 (3) | 0.000 | 0.000 | ✅ |
| Amount tier: mid (1k–10k) | 37 (16) | 0.000 | 0.000 | ✅ |
| Amount tier: high (>=10k) | 0 (0) | n/a | n/a | n/a |
| Segment: payroll | 9 (6) | 0.000 | 0.000 | ✅ |
| Segment: personal | 7 (2) | 0.000 | 0.000 | ✅ |
| Segment: trading | 10 (5) | 0.000 | 0.000 | ✅ |
| Segment: treasury | 11 (6) | 0.000 | 0.000 | ✅ |
| Segment: merchant settlement | 3 (0) | n/a | n/a | n/a |
| High-risk jurisdiction: no | 38 (18) | 0.000 | 0.000 | ✅ |
| High-risk jurisdiction: yes | 2 (1) | 0.000 | 0.000 | ✅ |

`data/bias_audit.json` is the machine-readable evidence pack. No slice failed the 0.10 parity threshold.

**Limitations:** the dataset is small and synthetic; two slices have no negative cases and therefore no estimable FPR. `account_purpose` and jurisdiction are coarse *proxies*, not protected attributes (the dataset contains no race, gender, age, or income labels). A zero-FPR result on this ledger is **not** evidence of fairness in production — it is a regression signal that must be recomputed on representative institutional data before deployment, with confidence intervals and protected-attribute collection handled under appropriate legal review.

---

## 5. Known threat boundaries

| Risk | Control in place | Remaining boundary |
|---|---|---|
| LLM01:2026 prompt injection (memo, RAG chunk, zero-width) | Regex/NFKC scan, XML sandbox, quarantine, HITL | Novel phrasings, multilingual or image/audio-encoded instructions are not detected by the scanner |
| LLM02:2026 sensitive information disclosure | Deterministic tokens at LangGraph **and** provider boundary; key-based + regex masking; metadata-only audit events | Masking relies on field names, regexes, and known names; an unrecognised identifier format in free text could pass through |
| LLM03:2026 excessive agency / ASI01:2026 goal hijack | No auto-close; grounded exoneration; deterministic adjudication; locked prompts | The model can still produce misleading narratives; analysts must rely on the verifier panel, not prose |
| LLM07:2026 misinformation | Citation/math verification, non-vacuous policy-citation rule, human flag | A model can cite a real policy that is semantically irrelevant; relevance is not machine-checked |
| LLM09:2026 vector weaknesses | Only versioned policy notes are searchable; no transaction vector search; poisoned chunks quarantined | Embedding inversion, access-control bypass at the vector store, and cross-tenant retrieval are out of scope |
| ASI09:2026 human-agent trust exploitation | Evidence-first review UI, disposition is advisory, analyst identity recorded | Automation bias in the human reviewer cannot be eliminated by code |
| A09:2025 logging & alerting failures | Append-only JSONL + optional `audit.security_events`; timestamp/case/category/action schema | No alerting backend is wired to the log; DB sink is fail-soft by design (JSONL is authoritative) |
| Supply chain, unbounded consumption, model theft, adversarial ML evasion | Not addressed by this prototype | Require platform-level controls (dependency pinning, rate limits, model registry, red-teaming) before production |

Residual risk is accepted only for the prototype scope. Deployment requires institutional validation, a live monitoring/alerting pipeline for the security event log, and periodic red-team exercises simulating goal override and RAG poisoning.
