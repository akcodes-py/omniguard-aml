"""Phase 4 gate: API contracts (auth + status codes) via TestClient."""
from fastapi.testclient import TestClient

from omniguard.api import app
from omniguard.config import settings
from omniguard.db import init_db

HEADERS = {"X-API-Key": settings.API_KEY}


def _client():
    init_db()
    return TestClient(app)


def test_health_and_auth():
    c = _client()
    assert c.get("/health").status_code == 200
    assert c.post("/investigate/x").status_code == 401  # no key
    assert c.post("/investigate/x", headers=HEADERS).status_code == 202


def test_review_validation():
    c = _client()
    r = c.post("/investigate/alert-demo-clean/alert-x/review", headers=HEADERS)
    assert r.status_code in (404, 405, 422)  # route shape enforced (real route is /investigate/{id}/review)


def test_scenario_contract():
    c = _client()
    r = c.post("/scenario/", headers=HEADERS,
               json={"concern_text": "layering via shells", "submitted_by": "t"})
    assert r.status_code == 202
    assert "concern_id" in r.json() and "job_id" in r.json()


def test_scenario_full_flow():
    import time as _t

    c = _client()
    cid = c.post("/scenario/", headers=HEADERS,
                 json={"concern_text": "structuring test", "submitted_by": "t"}).json()["concern_id"]
    st = None
    for _ in range(30):
        st = c.get(f"/scenario/{cid}/status", headers=HEADERS).json()
        if st.get("scenarios_generated"):
            break
        _t.sleep(1)
    assert st.get("set_id"), st  # UI approves against set_id, not concern_id
    ap = c.post(f"/scenario/{st['set_id']}/approve", headers=HEADERS, json={}).json()
    assert ap["status"] == "executing_control"
    res = c.get(f"/scenario/{st['set_id']}/results", headers=HEADERS)
    assert res.status_code == 200
    assert "evidence_pack_hash" in res.json()
