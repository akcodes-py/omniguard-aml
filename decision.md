# OmniGuard AML — Security Hardening Decision Log (ADRs)

This file records architectural decisions made during the "Regulated Data Encryption / API Hardening / OWASP 2026 Upgrade" task. Each decision is written so future maintainers understand *why* a choice was made and what was deliberately NOT changed.

---

## ADR-001 — Preserve existing pipelines; add security as a wrapper, not a rewrite
- **Status:** Accepted
- **Context:** OmniGuard already ships a verified dual-chain investigation pipeline, deterministic verifier, HITL gate, append-only audit triggers and a 54-test suite. The task explicitly forbids breaking them.
- **Decision:** Add new modules under `src/security/` and wire them into `api.py` via dependencies/middleware. Do not modify scoring, SHAP, NetworkX, LangGraph graphs, verifier logic or HITL rules. New behavior is opt-in via environment configuration where it could otherwise change existing responses.
- **Consequences:** Legacy endpoints continue to work. New security tests live in separate files. If an env key is absent, the app fails closed for auth-protected routes (401) rather than silently opening access.

## ADR-002 — AES-256-GCM field encryption with random 12-byte nonces
- **Status:** Accepted
- **Context:** Regulated account numbers / customer IDs must be encrypted at rest for compliance audits. Deterministic (searchable) encryption would leak equality; ECB/CBC lack integrity.
- **Decision:** Use `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a 32-byte base64 key from `ENCRYPTION_KEY`, a fresh `os.urandom(12)` nonce per value, and store `base64(nonce || ciphertext+tag)` as a string prefix (e.g. `enc:v1:...`) so ciphertext is self-describing. Wrap `InvalidTag` in `DecryptionTamperError`.
- **Consequences:** Ciphertext is randomized (same plaintext → different ciphertext), so equality search on encrypted columns is impossible by design; case search must use non-sensitive indexed fields (case id, status, assigned analyst). This is intentional — regulated identifiers are never used as filter keys.

## ADR-003 — PII masking stays before pgvector/LLM; encryption is a separate persistence-layer control
- **Status:** Accepted
- **Context:** Encryption at rest and masking in prompts solve different problems. Encrypt-then-mask would be wrong: masking needs structured plaintext, and ciphertext in prompts would break citation verification.
- **Decision:** Keep the existing deterministic PII masker at both LangGraph and provider boundaries. Field encryption is applied only when writing regulated identifiers to PostgreSQL, and decryption only when an authorized, assigned analyst views a case.
- **Consequences:** Raw PII never reaches logs, prompts, embeddings, or vector stores; ciphertext never reaches the LLM. Citation IDs remain intact.

## ADR-004 — Short-lived HS256 JWTs with explicit roles; ownership enforced per-case
- **Status:** Accepted
- **Context:** BOLA/IDOR is the top API risk: an analyst must not read another analyst's assigned case. Stateless HS256 keeps the service deployable without a session store.
- **Decision:** `POST /auth/login` verifies a bcrypt password hash and issues a JWT (`sub`, `role` ∈ {analyst, admin}, `exp`, `iat`, `iss`, `aud`) signed with `JWT_SECRET_KEY`. A FastAPI dependency extracts and validates the bearer token (HS256 only). Case routes take a `current_user` dependency and check `assigned_analyst == user.sub` (admins may bypass for compliance oversight, logged as a security event). `/investigate` accepts either the legacy `X-API-Key` (service principal) or a JWT so the existing UI/tests keep working.
- **Implementation note:** `passlib` 1.7.4 crashes with installed `bcrypt` 5.x (`bcrypt.__about__` removed), so `bcrypt.hashpw`/`checkpw` are used directly (still bcrypt, still cost 12).
- **Consequences:** Missing/expired/tampered tokens → 401. Cross-analyst access → 403. Admin access is auditable rather than silent.

## ADR-005 — Parameterized SQL only; no string interpolation for filters
- **Status:** Accepted (to be verified in code)
- **Context:** Case search accepts user-controlled `q`/filter parameters. Any f-string or `%` formatting into SQL is an injection sink.
- **Decision:** All case search/filter queries use bound parameters (`WHERE col = :value` / `%s` placeholders with a params tuple) through the existing DB abstraction. Free-text search uses parameterized `LIKE :pattern` with escaped wildcards.
- **Consequences:** SQLi payloads (`' OR '1'='1`, `'; DROP TABLE--`, `UNION SELECT`) are treated as literal strings and return zero rows, never a 500.

## ADR-006 — Rate limiting targets LLM/token-expensive endpoints (OWASP LLM06:2026)
- **Status:** Accepted
- **Context:** `/investigate` invokes dual LLM agents; unbounded consumption is LLM06:2026 (previously LLM10:2025). Brute-force on `/auth/login` is also a credential-stuffing vector.
- **Decision:** Use `slowapi` with `get_remote_address`; decorate `/auth/login` (strict), `/investigate` (moderate) and `/cases` (looser). Return a structured 429 with `Retry-After`.
- **Consequences:** Limits are per-IP and in-memory by default (documented as needing Redis behind multiple workers in production).

## ADR-007 — Security headers via lightweight ASGI middleware
- **Status:** Accepted
- **Context:** HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` mitigate browser-side attacks and satisfy API Top 10 hardening checks.
- **Decision:** Add a small pure-Starlette middleware that injects headers on every response. HSTS is only emitted when the request is TLS (or `TLS_ENABLED=true`) to avoid breaking local HTTP development.
- **Consequences:** No new heavyweight dependency; headers testable through `TestClient`.

## ADR-008 — OWASP 2026 taxonomy uses current IDs (not 2025 IDs)
- **Status:** Accepted
- **Context:** The existing code/README references 2025 IDs (e.g. "LLM06:2026 Unbounded Consumption" is correct for 2026, while "LLM07:2026 Misinformation" differs from 2025 LLM09). Agentic IDs ASI01/ASI02/ASI09 have specific 2026 meanings.
- **Decision:** Map tests and documentation to the 2026 IDs confirmed by OWASP GenAI Project sources (see `tracker.md`). Keep old test names working as aliases where the existing suite depends on them.
- **Consequences:** `SECURITY_ASSESSMENT.md` uses 2026 names; historical README text is updated to link to it rather than rewritten in place.

## ADR-009 — No hardcoded secrets; keys are required from env, loaded lazily
- **Status:** Accepted (refined during implementation of `src/security/encryption.py`)
- **Context:** Tests need deterministic keys; production must never ship with a baked-in key. Existing tests import `omniguard.api` without any security env vars set, so importing a module must not fail.
- **Decision:** Read `ENCRYPTION_KEY` and `JWT_SECRET_KEY` from env only. There is **no fallback key and no hardcoded secret**. Key resolution is lazy (on first encrypt/decrypt or token decode), so imports and the legacy suite remain unaffected. Tests supply real random keys via fixtures/CLI flags. `generate_key()` is provided for provisioning.
- **Consequences:** A missing key fails closed at first use with a clear `EncryptionConfigurationError` / 401 rather than silently weakening security. Documentation tells operators to generate and export keys before running the hardened endpoints.
