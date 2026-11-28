# OmniGuard AML — Security Hardening Progress Tracker

Task: Regulated Data Encryption (AES-256-GCM), API Auth/SQLi Hardening & OWASP 2026 Upgrade
Started: 2026-11-28

## Status legend
`[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked / issue

---

## Phase 0 — Inspect & plan
- [x] Load `web-research` skill; pull current OWASP 2026 references & library APIs
- [~] Inspect codebase (file map, routes, DB layer, config, tests, requirements) via explore agent
- [x] Create `tracker.md` and `decision.md`
- [ ] Research OWASP LLM Top 10 2026 / Agentic Top 10 2026 / API Top 10 mappings (done via web search — write up in Phase 3)

### Key external facts confirmed
- OWASP LLM Top 10 **2026**: LLM01 Prompt Injection, LLM02 Sensitive Info Disclosure, LLM03 Excessive Agency, LLM04 Supply Chain, LLM05 Data/Model Poisoning, LLM06 Unbounded Consumption, LLM07 Misinformation, LLM08 Hidden Context Exposure, LLM09 Vector/Embedding Weaknesses, LLM10 Improper Output Handling.
- OWASP Agentic (ASI) Top 10 **2026**: ASI01 Goal Hijack, ASI02 Tool Misuse & Exploitation, ASI03 Identity & Privilege Abuse, ASI04 Agentic Supply Chain, ASI05 Unexpected Code Execution (RCE), ASI06 Memory & Context Poisoning, ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Exploitation, ASI10 Rogue Agents.
- Library APIs verified via Context7: `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (12-byte nonce, `InvalidTag` on tamper), `PyJWT` (`jwt.encode`/`jwt.decode`, `algorithms=["HS256"]`, `exp`, `ExpiredSignatureError`), `passlib.hash.bcrypt` / `CryptContext`, `slowapi` (`Limiter`, `get_remote_address`, `@limiter.limit`, `RateLimitExceeded` handler with 429).

---

## Phase 1 — Field encryption, JWT/RBAC, rate limiting & headers
- [x] `src/security/encryption.py`: AES-256-GCM, base64 32-byte `ENCRYPTION_KEY` from env, `os.urandom(12)`, `DecryptionTamperError` on `InvalidTag`
- [x] Encrypt regulated identifiers (account numbers, customer IDs) at persistence boundary via `src/security/case_store.py` + new `cases` table (both SQL dialects); DB ciphertext assertion to be added in Phase 2 test
- [x] `src/security/auth.py`: `bcrypt` password hashing, short-lived HS256 JWT (`JWT_SECRET_KEY`), `analyst`/`admin` roles (passlib 1.7.4 is broken with bcrypt 5.x → use `bcrypt` directly, see ADR-004)
- [x] `POST /auth/login` endpoint
- [x] Protect `/investigate` (dual API-key/JWT), `/cases`, `/cases/{case_id}` with role + ownership/BOLA checks (403 for unassigned cases)
- [x] Parameterized SQL for all case search/filter queries (zero string interpolation)
- [x] `slowapi` rate limits on `/auth/login`, `/investigate`, `/cases` (429)
- [x] Security-headers middleware (HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy)
- [x] Regression check: 64/64 existing tests pass (`pytest -q`)

## Phase 2 — Automated security tests
- [x] `tests/test_encryption.py`: round-trip, unique nonces, tamper detection, DB ciphertext assertion
- [x] `tests/test_auth_idor_sqli.py`: missing/expired/tamper JWT -> 401, cross-analyst -> 403, SQLi payloads blocked with no 500s
- [x] `tests/test_owasp_2026.py`: LLM01/ASI01 indirect injection quarantine, LLM02 PII masking, LLM07 verifier rejects uncited claims, ASI02/ASI09 HITL (no auto-close of TP)
- [x] Existing suite still green — **81 tests pass total** (54 original + 11 encryption incl. DB ciphertext + 11 auth/IDOR/SQLi + 5 OWASP 2026)

## Phase 3 — VAPT artifacts & docs
- [x] `docs/omniguard_aml.postman_collection.json` (valid JSON, 6 folders)
- [x] `docs/BURP_SUITE_CHECKLIST.md` + `docs/security_evidence/README.md`
- [x] `SECURITY_ASSESSMENT.md` (threat model, OWASP LLM/Agentic/API mapping, 9 findings, CI results)
- [x] Update `.env.example` (ENCRYPTION_KEY, JWT_SECRET_KEY, TLS/rate-limit config)
- [x] Update `README.md` (Security Controls table, new endpoints, 81-test badge)

## Phase 4 — Verification
- [x] `pytest -v` → **81 passed**, 6 warnings
- [x] `bandit -r src/ -ll` → **0 findings, exit 0** (documented false-positive suppressions)
- [x] `pip-audit -r requirements.txt` → **No known vulnerabilities found** (project-scoped; F-08 updated)
- [x] `trivy` → not installed locally; tracked as F-09 for CI
- [x] Concise summary printed to user

---

## Progress notes
- 2026-11-28: Work begun. No source files modified yet (research/inspection only). No secrets will be hardcoded — all keys via env with dev-only fallbacks gated to non-production where unavoidable for testability.
