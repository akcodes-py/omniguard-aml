"""JWT auth, RBAC/BOLA and SQL-injection hardening tests (Phase 2)."""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from omniguard.api import app
from omniguard.config import settings
from omniguard.db import connect, fetchall, fetchone, init_db
from security import auth
from security.encryption import generate_key


@pytest.fixture(autouse=True)
def security_env(monkeypatch):
    """Fresh keys/users per test; no secrets are committed to source."""
    monkeypatch.setenv("ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-" + secrets.token_urlsafe(32))
    monkeypatch.setenv("JWT_TTL_MINUTES", "15")
    monkeypatch.setenv("TLS_ENABLED", "true")
    auth.clear_users()
    auth.register_user("alice", auth.hash_password("AlicePass123!"), "analyst")
    auth.register_user("bob", auth.hash_password("BobPass123!"), "analyst")
    auth.register_user("compliance", auth.hash_password("AdminPass123!"), "admin")
    init_db()
    yield
    auth.clear_users()


@pytest.fixture
def client():
    """Unique client IP isolates slowapi's in-memory counters per test."""
    ip = f"10.{secrets.randbelow(200) + 1}.{secrets.randbelow(200) + 1}.{secrets.randbelow(200) + 1}"
    return TestClient(app, client=(ip, 12345))


def _token(client, username: str, password: str) -> str:
    response = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_case(client, token: str, *, alert_id: str, account: str, customer: str = "") -> dict:
    response = client.post(
        "/cases",
        headers=_bearer(token),
        json={
            "alert_id": alert_id,
            "account_id": account,
            "customer_id": customer,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def test_login_issues_short_lived_role_token(client):
    response = client.post(
        "/auth/login", json={"username": "alice", "password": "AlicePass123!"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "analyst"
    assert body["expires_in"] == 15 * 60
    claims = auth.decode_access_token(body["access_token"])
    assert claims["sub"] == "alice" and claims["role"] == "analyst"


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/auth/login", json={"username": "alice", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_missing_malformed_expired_and_tampered_jwt_return_401(client):
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers={"Authorization": "Bearer garbage"}).status_code == 401

    expired = auth.create_access_token("alice", "analyst", ttl_minutes=-1)
    assert client.get("/cases", headers=_bearer(expired)).status_code == 401

    token = _token(client, "alice", "AlicePass123!")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert client.get("/cases", headers=_bearer(tampered)).status_code == 401
    assert client.get("/cases", headers=_bearer(token)).status_code == 200


def test_admin_role_required_for_admin_only_dependency(client):
    token = _token(client, "alice", "AlicePass123!")
    # Case routes accept analysts too; prove RBAC denies the wrong role using
    # the dependency directly (BFLA / API5:2023).
    with pytest.raises(Exception):
        auth.require_roles("admin")(user=auth.User(username="alice", role="analyst"))
    assert auth.require_roles("analyst", "admin")(
        user=auth.User(username="alice", role="analyst")
    ).username == "alice"
    assert token


# --------------------------------------------------------------------------- #
# BOLA / IDOR
# --------------------------------------------------------------------------- #
def test_cross_analyst_case_access_is_403(client):
    alice = _token(client, "alice", "AlicePass123!")
    bob = _token(client, "bob", "BobPass123!")
    admin = _token(client, "compliance", "AdminPass123!")

    case = _create_case(
        client, alice,
        alert_id="alert-idor-1",
        account="ACCT-SECRET-001",
        customer="CUST-SECRET-001",
    )
    case_id = case["case_id"]

    assert client.get(f"/cases/{case_id}", headers=_bearer(bob)).status_code == 403
    assert client.get(f"/cases/{case_id}").status_code == 401

    owned = client.get(f"/cases/{case_id}", headers=_bearer(alice))
    assert owned.status_code == 200
    assert owned.json()["account_id"] == "ACCT-SECRET-001"
    assert "account_id_enc" not in owned.json()

    # Compliance admins may cross-read, but the access is audited.
    assert client.get(f"/cases/{case_id}", headers=_bearer(admin)).status_code == 200


def test_analyst_cannot_assign_case_to_another_analyst(client):
    alice = _token(client, "alice", "AlicePass123!")
    response = client.post(
        "/cases",
        headers=_bearer(alice),
        json={
            "alert_id": "alert-bpla-1",
            "account_id": "ACCT-BPLA-1",
            "assigned_analyst": "bob",
        },
    )
    assert response.status_code == 403


def test_investigate_enforces_assignment_but_keeps_api_key(client):
    headers = {"X-API-Key": settings.API_KEY}
    assert client.post("/investigate/unassigned-alert").status_code == 401
    assert client.post("/investigate/unassigned-alert", headers=headers).status_code == 202

    alice = _token(client, "alice", "AlicePass123!")
    assert client.post(
        "/investigate/unassigned-alert", headers=_bearer(alice)
    ).status_code == 403

    _create_case(client, alice, alert_id="alert-assigned-1", account="ACCT-ASSIGNED-1")
    assert client.post(
        "/investigate/alert-assigned-1", headers=_bearer(alice)
    ).status_code == 202


# --------------------------------------------------------------------------- #
# SQL injection (API8:2023 / A03:2021)
# --------------------------------------------------------------------------- #
def test_sqli_payloads_are_inert_and_never_return_unauthorized_rows(client):
    alice = _token(client, "alice", "AlicePass123!")
    bob = _token(client, "bob", "BobPass123!")
    _create_case(client, alice, alert_id="alert-sqli-alice", account="ACCT-SQLI-A")
    _create_case(client, bob, alert_id="alert-sqli-bob", account="ACCT-SQLI-B")

    con = connect()
    try:
        before = fetchall(con.cursor(), "SELECT case_id FROM cases")
    finally:
        con.close()

    # Baseline: the endpoint works normally for the assigned analyst.
    baseline = client.get(
        "/cases", headers=_bearer(alice), params={"q": "alert-sqli-alice"}
    )
    assert baseline.status_code == 200
    baseline_rows = baseline.json()["cases"]
    assert baseline_rows
    assert all(r["assigned_analyst"] == "alice" for r in baseline_rows)
    assert "alert-sqli-alice" in {r["alert_id"] for r in baseline_rows}
    assert "alert-sqli-bob" not in {r["alert_id"] for r in baseline_rows}

    payloads = [
        "' OR '1'='1",
        "'; DROP TABLE cases;--",
        "UNION SELECT username, password_hash FROM users--",
        "%' OR 1=1--",
        "_' OR 1=1--",
    ]
    for payload in payloads:
        response = client.get("/cases", headers=_bearer(alice), params={"q": payload})
        assert response.status_code == 200, (payload, response.text)
        rows = response.json()["cases"]
        assert rows == [], f"injection payload matched rows: {payload}"
        assert all(r["assigned_analyst"] == "alice" for r in rows)

    con = connect()
    try:
        after = fetchall(con.cursor(), "SELECT case_id FROM cases")
        probe = fetchone(con.cursor(), "SELECT 1 AS ok")
    finally:
        con.close()
    assert len(after) == len(before), "injection payload must not drop rows"
    assert probe["ok"] == 1, "cases table still exists after DROP TABLE payload"


def test_sql_status_filter_is_parameterized(client):
    alice = _token(client, "alice", "AlicePass123!")
    response = client.get(
        "/cases",
        headers=_bearer(alice),
        params={"status": "OPEN' OR '1'='1"},
    )
    assert response.status_code == 200
    assert response.json()["cases"] == []


# --------------------------------------------------------------------------- #
# Rate limiting & headers
# --------------------------------------------------------------------------- #
def test_login_rate_limit_returns_429(monkeypatch, client):
    monkeypatch.setattr(auth, "authenticate", lambda username, password: None)
    status_codes = [
        client.post(
            "/auth/login", json={"username": "alice", "password": "whatever"}
        ).status_code
        for _ in range(22)
    ]
    assert 429 in status_codes, status_codes


def test_security_headers_on_every_response(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
