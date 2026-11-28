# Security Evidence — OmniGuard AML

Live VAPT evidence. **These are genuine HTTP responses from a running OmniGuard instance**, captured
in Chromium with Playwright. Burp Suite is not installed in this environment, so no Burp UI
screenshots are claimed — the request details, statuses and response bodies are real and
reproducible with the harness below.

## Files

| File | Check | Result |
|---|---|---|
| `AUTH-04_tampered-jwt-401.png` | Tampered HS256 bearer token on `GET /cases` | `401 Unauthorized` + `WWW-Authenticate: Bearer` |
| `IDOR-01_cross-analyst-403.png` | Bob's JWT reading Alice's case (`GET /cases/{case_id}`) | `403 Forbidden` — BOLA/IDOR defense |
| `RATE-01_login-429.png` | 22 login attempts from one IP (limit 20/min) | `429 Too Many Requests` — `20 per 1 minute` |
| `evidence.html` | Harness page used to drive the three tests | — |

## Reproduce

```powershell
# 1. Start a throwaway API with ephemeral keys/users and one seeded case (port 8011)
python scripts/evidence_server.py

# 2. Serve the harness on the CORS-allowed origin (port 5173)
python -m http.server 5173 --bind 127.0.0.1 --directory docs/security_evidence

# 3. Open http://127.0.0.1:5173/evidence.html and wait for the three cards to resolve
```

Port 8011 is used because port 8000 is occupied by an unrelated local service.
All keys/tokens in the harness are generated at runtime; **nothing is committed**.
Test data is synthetic (`ACCT-VAPT-0001`, `CUST-VAPT-0001`).

## Caveats

- Captured in a browser, not Burp Repeater — see `docs/BURP_SUITE_CHECKLIST.md` to reproduce
  the same requests in Burp on your own machine and add Burp screenshots if needed.
- `Retry-After` appears as `—` in the 429 card because the browser hides that response header
  from cross-origin JavaScript unless CORS exposes it; the server does send it (see `api.py`).
