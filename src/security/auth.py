"""JWT authentication, RBAC and object-level authorization (BOLA/IDOR).

Design notes
------------
* HS256 tokens are short-lived and carry ``sub``, ``role``, ``iat`` and ``exp``.
  The signing secret comes **only** from ``JWT_SECRET_KEY`` (no hardcoded key).
* Passwords are hashed with ``bcrypt`` directly. ``passlib`` 1.7.4 is
  incompatible with bcrypt 5.x (``bcrypt.__about__`` was removed), so the
  CryptContext wrapper is deliberately avoided here.
* Roles: ``analyst`` (scoped to assigned cases) and ``admin`` (compliance
  oversight; every cross-case read is written to the security event log).
* The API-key path used by the legacy UI/worker is represented as a
  ``service`` principal so existing callers keep working while new endpoints
  require a real JWT.

No user passwords are hardcoded. Users are provisioned either through
``OMNIGUARD_USERS_JSON`` (a JSON list of username / bcrypt hash / role) or at
runtime via :func:`register_user` (used by bootstrap scripts and tests).
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWTError

__all__ = [
    "ROLES",
    "AuthConfigurationError",
    "AuthError",
    "User",
    "authenticate",
    "clear_users",
    "create_access_token",
    "decode_access_token",
    "enforce_case_access",
    "get_current_user",
    "hash_password",
    "load_users_from_env",
    "register_user",
    "require_roles",
    "verify_password",
]

ROLES = ("analyst", "admin")
SERVICE_ROLE = "service"
_JWT_ISSUER = "omniguard-aml"
_JWT_AUDIENCE = "omniguard-api"


class AuthError(Exception):
    """Raised for any invalid, expired or tampered token."""


class AuthConfigurationError(RuntimeError):
    """Raised when JWT_SECRET_KEY is missing or too weak."""


@dataclass(frozen=True)
class User:
    """Authenticated principal. ``role`` is one of analyst/admin/service."""

    username: str
    role: str
    password_hash: str = ""
    display_name: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_service(self) -> bool:
        return self.role == SERVICE_ROLE


# --------------------------------------------------------------------------- #
# Password hashing (bcrypt)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a bcrypt hash (cost 12) for *password*."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time bcrypt verification; never raises on malformed input."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("ascii"))
    except (ValueError, TypeError, AttributeError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Used for unknown usernames to keep login timing comparable."""
    return hash_password(secrets.token_hex(16))


# --------------------------------------------------------------------------- #
# User registry
# --------------------------------------------------------------------------- #
_USERS: dict[str, User] = {}


def register_user(
    username: str,
    password_hash: str,
    role: str = "analyst",
    display_name: str = "",
) -> User:
    """Register (or replace) a user. ``password_hash`` must be a bcrypt hash."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username:
        raise ValueError("username is required")
    user = User(username=username, role=role, password_hash=password_hash,
                display_name=display_name or username)
    _USERS[username] = user
    return user


def clear_users() -> None:
    """Remove all registered users (test/bootstrap convenience)."""
    _USERS.clear()


def load_users_from_env() -> None:
    """Load ``OMNIGUARD_USERS_JSON`` into the registry (called at import)."""
    raw = os.getenv("OMNIGUARD_USERS_JSON", "").strip()
    if not raw:
        return
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthConfigurationError("OMNIGUARD_USERS_JSON is not valid JSON") from exc
    if not isinstance(entries, list):
        raise AuthConfigurationError("OMNIGUARD_USERS_JSON must be a JSON list")
    for entry in entries:
        register_user(
            username=str(entry["username"]),
            password_hash=str(entry["password_hash"]),
            role=str(entry.get("role", "analyst")),
            display_name=str(entry.get("display_name", "")),
        )


def authenticate(username: str, password: str) -> Optional[User]:
    """Return the user when the bcrypt password matches, else ``None``."""
    user = _USERS.get(username)
    if user is None:
        verify_password(password, _dummy_hash())
        return None
    return user if verify_password(password, user.password_hash) else None


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise AuthConfigurationError(
            "JWT_SECRET_KEY is not set. Generate one (e.g. "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\") "
            "and export it before starting the API."
        )
    if len(secret) < 32:
        raise AuthConfigurationError("JWT_SECRET_KEY must be at least 32 characters")
    return secret


def create_access_token(
    username: str,
    role: str,
    ttl_minutes: Optional[int] = None,
    *,
    secret: Optional[str] = None,
) -> str:
    """Issue a short-lived HS256 bearer token."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if ttl_minutes is None:
        ttl_minutes = int(os.getenv("JWT_TTL_MINUTES", "15"))
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
    }
    return jwt.encode(payload, secret or _jwt_secret(), algorithm="HS256")


def decode_access_token(token: str, *, secret: Optional[str] = None) -> dict[str, Any]:
    """Validate signature/claims; raise :class:`AuthError` on any failure."""
    try:
        payload = jwt.decode(
            token,
            secret or _jwt_secret(),
            algorithms=["HS256"],
            audience=_JWT_AUDIENCE,
            issuer=_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "role"]},
        )
    except (PyJWTError, AuthConfigurationError, ValueError) as exc:
        raise AuthError("Invalid or expired bearer token") from exc
    if payload.get("role") not in ROLES:
        raise AuthError("Invalid role claim")
    return payload


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Missing, expired or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> User:
    """FastAPI dependency: require a valid HS256 bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except AuthError as exc:
        raise _unauthorized() from exc
    return User(username=str(claims["sub"]), role=str(claims["role"]))


def require_roles(*roles: str):
    """Dependency factory enforcing role-level authorization (BFLA, API5)."""
    allowed = set(roles) or set(ROLES)

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return _dependency


def _audit(case_id: str, action: str, details: dict[str, Any]) -> None:
    """Append an object-level authorization event (fail-soft)."""
    try:
        from .audit_logger import A09, log_security_event

        log_security_event(
            case_id=case_id,
            owasp_category=A09,
            action_taken=action,
            details=details,
        )
    except Exception:  # noqa: BLE001 - audit outage must not block auth decisions
        pass


def enforce_case_access(case_id: str, user: User, assigned_analyst: str) -> None:
    """Enforce object-level authorization (BOLA/IDOR, API1:2023).

    Analysts may only access cases assigned to them. Admins may cross-read for
    compliance oversight, but each such access is recorded in the append-only
    security event log. Service principals (legacy API key) are trusted.
    """
    if user.is_service or user.is_admin:
        if user.is_admin and not secrets.compare_digest(assigned_analyst, user.username):
            _audit(case_id, "ADMIN_CROSS_CASE_ACCESS",
                   {"role": user.role, "assigned_analyst": assigned_analyst})
        return
    if not secrets.compare_digest(user.username, str(assigned_analyst)):
        _audit(case_id, "BOLA_ACCESS_DENIED",
               {"role": user.role, "requested_by": user.username})
        raise HTTPException(status_code=403, detail="Case is not assigned to this analyst")


load_users_from_env()
