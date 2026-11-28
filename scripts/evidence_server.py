"""Reproducible local VAPT harness server (no secrets committed).

Generates ephemeral keys/users, seeds one assigned case, then serves the API
so the browser evidence page can capture real 401/403/429 responses.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["ENCRYPTION_KEY"] = (
    __import__("security.encryption", fromlist=["generate_key"]).generate_key()
)
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)

from security import auth  # noqa: E402
from security.case_store import create_case  # noqa: E402
from omniguard.db import init_db  # noqa: E402

auth.register_user("alice", auth.hash_password("AlicePass123!"), "analyst")
auth.register_user("bob", auth.hash_password("BobPass123!"), "analyst")
init_db()
case = create_case(
    alert_id="alert-vapt-evidence",
    account_id="ACCT-VAPT-0001",
    customer_id="CUST-VAPT-0001",
    assigned_analyst="alice",
)
print(f"[evidence] case_id={case['case_id']}", flush=True)

import uvicorn  # noqa: E402

uvicorn.run("omniguard.api:app", host="127.0.0.1", port=8011, log_level="warning")
