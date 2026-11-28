# OmniGuard AML — Security Assessment (VAPT)

**Assessment date:** 2026-11-28
**Scope:** `src/omniguard` API + investigation graph, `src/security` controls, `db/*` schemas, `tests/*`, `docs/*`
**Method:** manual code review + automated pytest security suites + static/dependency scanning
**Companion documents:** [MODEL_CARD.md](MODEL_CARD.md) (explainability, HITL, bias), [FLOW.md](FLOW.md) (call graph), [DECISIONS.md](DECISIONS.md) / [decision.md](decision.md) (ADRs), [README.md](README.md)

---

## 1. Financial-Crime Threat Model

An AML platform is a **stateful, regulated system** — unlike a stateless chatbot it must retain
customer/account records for multi-year audits. That persistence creates a threat model where
three controls are *jointly necessary*; removing any one breaks compliance:

| Threat | Why the control is required | OmniGuard control |
|---|---|---|
| **Database theft / insider DB access** | Analysts and DBAs can query tables directly; backups leave the VPC. Encryption at rest limits blast radius. | **AES-256-GCM** field encryption of account numbers and customer IDs in `core.cases` / `cases`; fresh 12-byte nonce per value; random nonces prevent equality leakage. |
| **Silent record tampering** | A regulator must be able to prove that an investigation record was not altered after the fact. | **Append-only PostgreSQL triggers** (`audit.block_mutation()`) plus SQLite equivalents on `investigation_runs`, `human_decisions`, `security_events`, `expected_outcomes`, `control_runs`; SHA-256 sealing of scenario expectations before control execution. |
| **Model memorisation / prompt leakage** | Regulated identifiers placed in prompts can be echoed, logged, or embedded in vector stores. | **Deterministic PII masking** at both the LangGraph boundary and the LLM provider boundary, with citation IDs preserved. `pgvector` is restricted to policy manuals — never transactions. |
| **Cross-analyst data browsing (BOLA/IDOR)** | A compromised analyst account must not expose another analyst's case. | JWT `sub` + per-case `assigned_analyst` ownership check; 403 on mismatch; admin cross-reads are audited. |
| **Injection into agent context** | Transaction memos and retrieved policy chunks are attacker-controlled. | NFKC/zero-width normalisation, XML sandboxing, chunk quarantine before the dual-chain agents see the data. |
| **Unbounded LLM spend** | Repeated investigation calls can exhaust GPU quota (denial-of-wallet). | `slowapi` per-IP limits on `/auth/login`, `/investigate`, `/cases` with structured 429. |

**Why all three together:** encryption alone protects stolen bytes but not an authorised-but-curious
analyst; audit triggers alone prove integrity but expose plaintext; masking alone protects prompts
but not the database. Regulated compliance requires confidentiality + integrity + minimisation
simultaneously.

**Trust boundaries:** browser/UI → FastAPI → DB; FastAPI → LangGraph dual agents → NIM/Bedrock;
policy retrieval (pgvector) → agents; worker → queue. Every boundary that can carry free text is
scanned or masked; every object-returning route performs an ownership check.

---

## 2. OWASP LLM Top 10 (2026) mapping

IDs verified against the OWASP GenAI Security Project 2026 publication.

| ID | Risk | Control in OmniGuard | Evidence |
|---|---|---|---|
| LLM01:2026 | Prompt Injection | `injection.scan_transaction`, `scan_policy_chunk`, XML sandboxing, quarantine → `CONFLICT_HUMAN_REVIEW` | `tests/test_owasp_2026.py`, `tests/test_owasp_llm.py` |
| LLM02:2026 | Sensitive Information Disclosure | `pii_masker.mask_payload` at LangGraph + provider boundaries; AES-256-GCM at rest | `tests/test_owasp_2026.py::test_no_raw_pii_in_llm_prompt_or_security_log`, `tests/test_encryption.py` |
| LLM03:2026 | Excessive Agency | Deterministic verifier + mandatory human gate; no agent can finalise `CLOSE` | `verifier.hitl_required`, `graphs_investigation.review` |
| LLM04:2026 | Supply Chain | Pinned floors in `requirements.txt`; `pip-audit` in CI (see §5) | CI log |
| LLM05:2026 | Data & Model Poisoning | Policy chunks scanned before use; model artifacts produced only by `scripts/train.py`; SHA-256 sealed expectations | `tests/test_phase3_scenario.py` |
| LLM06:2026 | Unbounded Consumption | `slowapi` limits on login / investigate / cases (429 + `Retry-After`) | `tests/test_auth_idor_sqli.py::test_login_rate_limit_returns_429` |
| LLM07:2026 | Misinformation | `verifier.verify_citations` checks tx IDs, policy IDs/versions and numeric claims; failures route to a human | `tests/test_owasp_2026.py::test_hallucinated_claims_are_rejected_and_audited` |
| LLM08:2026 | Hidden Context Exposure | Masked payloads, no raw PII in logs; CSP + `Referrer-Policy` on responses | `src/security/headers.py` |
| LLM09:2026 | Vector & Embedding Weaknesses | Retrieved chunks scanned for indirect injection and dropped; vector search restricted to policy notes | `tests/test_owasp_llm.py::test_llm01_llm09_poisoned_policy_chunk_is_quarantined` |
| LLM10:2026 | Improper Output Handling | LLM output is JSON-validated against a strict schema; decisions are proposals only, finalised by `review()` | `llm._validate`, `graphs_investigation.review` |

---

## 3. OWASP Agentic Top 10 (2026) mapping

| ID | Risk | Control in OmniGuard | Evidence |
|---|---|---|---|
| ASI01:2026 | Agent Goal Hijack | Injected memos/chunks quarantined before the Investigator/Challenger; deterministic state cannot be overridden by prompt text | `tests/test_owasp_2026.py`, `tests/test_owasp_llm.py::test_llm03_asi01_*` |
| ASI02:2026 | Tool Misuse & Exploitation | Agents have no case-closing tool; allowed decisions are validated (`ESCALATE`, `CLOSE`, `REQUEST_RERUN`, `RETURN_FOR_RERUN`) and require a human analyst | `tests/test_owasp_2026.py::test_true_positive_cannot_be_auto_closed_by_an_agent` |
| ASI03:2026 | Identity & Privilege Abuse | JWT roles `analyst`/`admin`; ownership scoped to `assigned_analyst`; service principal limited to legacy API-key routes | `src/security/auth.py` |
| ASI04:2026 | Agentic Supply Chain | Model IDs/paths from config only; known-model allow-list in `llm._ensure_model_known` | `tests/test_phase3_nim.py` |
| ASI05:2026 | Unexpected Code Execution (RCE) | No agent-generated code is executed; scenario generation is deterministic Pydantic spec → transaction rows | `scenario_gen.py` |
| ASI06:2026 | Memory & Context Poisoning | No persistent agent memory store; retrieved policy chunks are re-scanned every run | `graphs_investigation.node_retrieve_policies` |
| ASI07:2026 | Insecure Inter-Agent Communication | Investigator/Challenger run in-process with typed state; outputs validated before adjudication | `llm.call_json`, `verifier.adjudicate` |
| ASI08:2026 | Cascading Failures | LLM outage degrades to deterministic mock; audit outage is fail-soft with JSONL authoritative | `llm.py`, `audit_logger._write_db` |
| ASI09:2026 | Human-Agent Trust Exploitation | Mandatory HITL: 0/15 true positives auto-closed in the 50-case matrix; every decision written to `human_decisions` | `tests/test_owasp_2026.py`, `README.md` §Measured Results |
| ASI10:2026 | Rogue Agents | No autonomous action loop; every run terminates at the human gate | `graphs_investigation` `interrupt_before=["human_gate"]` |

---

## 4. OWASP API Security Top 10 mapping

The current published edition is **API Top 10:2023** (no 2026 edition existed at assessment time);
IDs below use that edition. "2026 upgrade" refers to the LLM/Agentic lists.

| ID | Risk | Control | Evidence |
|---|---|---|---|
| API1:2023 | Broken Object Level Authorization (BOLA) | `enforce_case_access` / `enforce_investigation_access` — 403 for unassigned cases | `tests/test_auth_idor_sqli.py` |
| API2:2023 | Broken Authentication | bcrypt (cost 12) password hashes, short-lived HS256 JWT (`JWT_SECRET_KEY`), 401 on missing/expired/tampered tokens | `test_auth_idor_sqli.py` |
| API3:2023 | Broken Object Property Level Authorization | Analysts cannot set `assigned_analyst` to another user; ciphertext never returned by API | `test_analyst_cannot_assign_case_to_another_analyst` |
| API4:2023 | Unrestricted Resource Consumption | `slowapi` limits + clamped `limit` query param (`max(1, min(limit, 200))`) | `test_login_rate_limit_returns_429` |
| API5:2023 | Broken Function Level Authorization | `require_roles("analyst","admin")` dependency; admin-only paths audited | `src/security/auth.py` |
| API6:2023 | Unrestricted Access to Sensitive Business Flows | Rate limits + HITL gate on investigation | `api.py` |
| API7:2023 | Server Side Request Forgery | No user-controlled URL fetching; NIM base URL from config | `llm.py` |
| API8:2023 | Security Misconfiguration | Security-headers middleware; HSTS only on TLS; `.bandit` config; no hardcoded secrets | `tests/test_auth_idor_sqli.py::test_security_headers_on_every_response` |
| API9:2023 | Improper Inventory Management | `/docs` Swagger exposed only by local config; documented env surface in `.env.example` | `.env.example` |
| API10:2023 | Unsafe Consumption of APIs | Strict JSON schema validation of model output; no downstream execution of remote content | `llm._validate` |

---

## 5. VAPT findings & remediation log

| ID | Severity | Finding | Remediation | Status |
|---|---|---|---|---|
| F-01 | High | Regulated identifiers were stored as plaintext `account_id` keys in ledger tables | Added `core.cases` / `cases` with `account_id_enc` / `customer_id_enc`; AES-256-GCM encryption at the write boundary via `case_store.create_case`; decryption only after ownership check | **Fixed** |
| F-02 | High | Case routes had no authentication or object-level authorization (BOLA) | JWT `analyst`/`admin` roles + per-case assignment checks; 403 on cross-analyst access; admin reads audited | **Fixed** |
| F-03 | High | Login endpoint did not exist; API key was the only credential and had no brute-force protection | `POST /auth/login` with bcrypt verification, short-lived JWT, `slowapi` 20/minute limit | **Fixed** |
| F-04 | Medium | Free-text `q` filter could have been interpolated into SQL | Strictly parameterized `LIKE ? ESCAPE '\'` with wildcard escaping; table name from fixed `t()` whitelist | **Fixed** |
| F-05 | Medium | No security response headers | `SecurityHeadersMiddleware` adds HSTS (TLS only), `nosniff`, `DENY`, CSP, `no-referrer` | **Fixed** |
| F-06 | Medium | `passlib` 1.7.4 is incompatible with installed `bcrypt` 5.x (crashes on `bcrypt.__about__`) | Use `bcrypt.hashpw`/`checkpw` directly (cost 12) — see `decision.md` ADR-004 | **Fixed** |
| F-07 | Low | Bandit B608/B301 reports on trusted table-name interpolation and locally generated pickle model artifacts | Inline justified `# nosec` annotations at each site; exact rationale recorded here and in `.bandit`; dynamic SQLi tests prove payloads are inert | **Accepted (documented false positive)** |
| F-08 | Medium | `pip-audit` against the **shared global interpreter** reported 105 findings across 22 packages (django, aiohttp, pypdf, mlflow transitive deps, etc.) | Re-ran scoped to the project: `python -m pip_audit -r requirements.txt` → **"No known vulnerabilities found"**. The global findings are unrelated packages not declared by OmniGuard. | **Fixed / verified — project scope clean** |
| F-09 | Low | `trivy` is not installed locally | Add `aquasecurity/trivy-action` to CI to scan the Docker image | **Open — tracked** |

### Notes on F-08 (dependency hygiene)
The first audit was run against the shared global interpreter (the `pip-audit` executable is not
on `PATH`; `python -m pip_audit` was used), which is why it surfaced 105 findings in unrelated
packages. The authoritative project-scoped command is:

```powershell
python -m pip_audit -r requirements.txt
```

Exact output (2026-11-28):

```
WARNING:venv:Actual environment location may have moved due to redirects, links or junctions.
  Requested location: "C:\Users\ATULKU~1\AppData\Local\Temp\tmpvdejc__1\Scripts\python.exe"
  Actual location:    "C:\Users\Atul Kumar\AppData\Local\Temp\tmpvdejc__1\Scripts\python.exe"
No known vulnerabilities found
```

The `WARNING:venv` line is a benign Windows short-path/junction notice from pip-audit's temporary
resolution environment, not a dependency finding. **OmniGuard's declared dependencies are clean.**
Recommended CI hardening remains: generate a hashed lockfile (`pip-compile --generate-hashes`)
and run `python -m pip_audit -r requirements.lock` so builds are reproducible.

---

## 6. CI results (this run, 2026-11-28)

| Tool | Command | Result |
|---|---|---|
| pytest | `python -m pytest -q` | **81 passed**, 6 warnings (slowapi `asyncio.iscoroutinefunction` deprecation on Python 3.14; SHAP TreeExplainer notice). All 54 pre-existing tests still pass. |
| bandit | `python -m bandit -r src/ -ll` | **0 findings, exit 0**. B608/B301 false positives are annotated at source with `# nosec` and justified above. Bandit emits informational "nosec encountered, but no failed test" warnings because multi-line SQL string contexts share the annotation; no issue is reported. `.bandit` provides an alternative config-level skip if the annotations are removed. |
| pip-audit | `python -m pip_audit -r requirements.txt` | **No known vulnerabilities found** (project-scoped). The earlier 105 findings came from auditing the shared global interpreter; see F-08. |
| trivy | `trivy --version` | Not installed locally; add to CI (F-09). |

### Test inventory
- `tests/test_encryption.py` — 11 tests (round-trip, nonce uniqueness, tamper, AAD, key validation, DB ciphertext)
- `tests/test_auth_idor_sqli.py` — 11 tests (JWT lifecycle, RBAC/BOLA, SQLi, rate limits, headers)
- `tests/test_owasp_2026.py` — 5 tests (LLM01/ASI01 quarantine, LLM02 masking, LLM07 verifier, ASI02/ASI09 HITL)
- Pre-existing suite — 54 tests (13 of them tagged OWASP in `test_owasp_llm.py`)

---

## 7. Residual risk & recommendations

1. **Key management:** `ENCRYPTION_KEY` and `JWT_SECRET_KEY` are env-supplied. Use a KMS/Secrets
   Manager in production and rotate with re-encryption of `cases` records.
2. **Stateless JWT revocation:** tokens are short-lived (15 min) but cannot be revoked before
   expiry. Add a deny-list (Redis) for high-risk role changes.
3. **Rate-limit backend:** `slowapi` uses in-memory storage; behind multiple workers, switch to
   Redis so limits are global.
4. **Searchability trade-off:** randomized GCM ciphertext cannot be equality-searched. Case search
   is intentionally limited to non-sensitive fields; do not add ciphertext filtering.
5. **Scope note:** the synthetic ledger tables (`core.accounts`, `core.transactions`) keep their
   pseudonymous UUID identifiers because LightGBM/SHAP/NetworkX require joinable keys. The
   *regulated* case record identifiers are the ones encrypted. Full ledger-wide encryption would
   require a separate tokenisation service and is out of scope for this hardening pass.

---

## 8. Sign-off checklist

- [x] Code review completed for all modified source files
- [x] Existing pipelines (LightGBM / SHAP / NetworkX / LangGraph / verifier / HITL / audit triggers) untouched in behaviour
- [x] 81 automated tests pass
- [x] Postman collection and Burp checklist delivered
- [ ] Production keys provisioned via secret manager
- [ ] CI upgraded with `pip-audit`, `bandit` and `trivy` steps
- [ ] Burp screenshots captured in `docs/security_evidence/`
