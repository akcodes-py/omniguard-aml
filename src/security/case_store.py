"""Case persistence with AES-256-GCM encrypted regulated identifiers.

All user-controlled values are **bound parameters**. The only interpolated SQL
fragment is the table name, which comes from the fixed whitelist in
``omniguard.db.t()`` — never from request input.

Regulated identifiers (account number, customer ID) are encrypted before they
reach the database and decrypted only after object-level authorization has
succeeded. Search/filter is restricted to non-sensitive fields (case ID,
alert ID, assigned analyst, status) because randomized GCM nonces make
equality search on ciphertext impossible by design.
"""
from __future__ import annotations

import secrets
import uuid
from typing import Any, Optional

from fastapi import HTTPException

from omniguard.db import connect, fetchall, fetchone, run, t

from .auth import User, enforce_case_access
from .encryption import (
    DecryptionTamperError,
    EncryptionConfigurationError,
    decrypt,
    encrypt,
)

__all__ = [
    "AAD_ACCOUNT",
    "AAD_CUSTOMER",
    "create_case",
    "enforce_investigation_access",
    "get_case",
    "list_cases",
]

AAD_ACCOUNT = "cases.account_id_enc"
AAD_CUSTOMER = "cases.customer_id_enc"


def _like_pattern(value: str) -> str:
    """Escape LIKE wildcards so a user cannot broaden the search."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def create_case(
    *,
    alert_id: str,
    account_id: str,
    customer_id: str = "",
    assigned_analyst: str,
) -> dict[str, Any]:
    """Insert a case with encrypted regulated identifiers.

    Returns only non-sensitive metadata — never the plaintext identifiers.
    """
    case_id = uuid.uuid4().hex
    account_enc = encrypt(str(account_id), aad=AAD_ACCOUNT)
    customer_enc = encrypt(str(customer_id), aad=AAD_CUSTOMER) if customer_id else ""

    con = connect()
    try:
        cur = con.cursor()
        run(
            cur,
            f"INSERT INTO {t('cases')} "  # nosec B608 - table name from fixed t() whitelist, all values bound
            "(case_id, alert_id, account_id_enc, customer_id_enc, assigned_analyst, status) "
            "VALUES (?,?,?,?,?,'OPEN')",
            (case_id, alert_id, account_enc, customer_enc, assigned_analyst),
        )
        con.commit()
    finally:
        con.close()
    return {
        "case_id": case_id,
        "alert_id": alert_id,
        "assigned_analyst": assigned_analyst,
        "status": "OPEN",
    }


def list_cases(
    user: User,
    *,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List cases visible to *user*, using strictly parameterized filters."""
    where: list[str] = []
    params: list[Any] = []

    # Defense in depth: analysts only ever see their own assignments.
    if not (user.is_admin or user.is_service):
        where.append("assigned_analyst = ?")
        params.append(user.username)
    if status:
        where.append("status = ?")
        params.append(status)
    if q:
        pattern = _like_pattern(q)
        where.append(
            "(case_id LIKE ? ESCAPE '\\' OR alert_id LIKE ? ESCAPE '\\' "
            "OR assigned_analyst LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])

    clause = " WHERE " + " AND ".join(where) if where else ""
    params.append(max(1, min(limit, 200)))

    con = connect()
    try:
        cur = con.cursor()
        return fetchall(
            cur,
            f"SELECT case_id, alert_id, assigned_analyst, status, created_at "  # nosec B608 - table name from fixed t() whitelist, all values bound
            f"FROM {t('cases')}{clause} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
    finally:
        con.close()


def get_case(user: User, case_id: str) -> dict[str, Any]:
    """Fetch one case; decrypt identifiers only for an authorized principal."""
    con = connect()
    try:
        cur = con.cursor()
        row = fetchone(cur, f"SELECT * FROM {t('cases')} WHERE case_id=?", (case_id,))  # nosec B608 - table name from fixed t() whitelist, all values bound
    finally:
        con.close()
    if not row:
        raise HTTPException(status_code=404, detail="case not found")

    enforce_case_access(case_id, user, row["assigned_analyst"])

    result = dict(row)
    raw_account = row.get("account_id_enc") or ""
    raw_customer = row.get("customer_id_enc") or ""
    try:
        result["account_id"] = decrypt(raw_account, aad=AAD_ACCOUNT) if raw_account else ""
        result["customer_id"] = decrypt(raw_customer, aad=AAD_CUSTOMER) if raw_customer else ""
    except DecryptionTamperError as exc:
        try:
            from .audit_logger import A09, log_security_event

            log_security_event(
                case_id=case_id,
                owasp_category=A09,
                action_taken="CIPHERTEXT_INTEGRITY_FAILURE",
                details={"field": "case_identifiers"},
            )
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=409, detail="Encrypted case fields failed integrity check") from exc
    except EncryptionConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Field decryption is not configured") from exc

    # Ciphertext is an implementation detail; never return it to clients.
    result.pop("account_id_enc", None)
    result.pop("customer_id_enc", None)
    return result


def cases_for_alert(alert_id: str) -> list[dict[str, Any]]:
    """Return assignment metadata for cases linked to an alert."""
    con = connect()
    try:
        cur = con.cursor()
        return fetchall(
            cur,
            f"SELECT case_id, assigned_analyst FROM {t('cases')} WHERE alert_id=?",  # nosec B608 - table name from fixed t() whitelist, all values bound
            (alert_id,),
        )
    finally:
        con.close()


def enforce_investigation_access(user: User, alert_id: str) -> None:
    """Block analysts from investigating alerts assigned to other analysts."""
    if user.is_service or user.is_admin:
        return
    rows = cases_for_alert(alert_id)
    if not any(
        secrets.compare_digest(str(r["assigned_analyst"]), user.username)
        for r in rows
    ):
        raise HTTPException(
            status_code=403,
            detail="Alert is not assigned to this analyst",
        )
