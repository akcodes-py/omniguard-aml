"""DB layer: Postgres (canonical) with SQLite local fallback.

- Postgres when DATABASE_URL scheme is postgresql/postgres (psycopg sync).
- SQLite otherwise (stdlib sqlite3). Schema applied from
  db/schema_sqlite.sql; canonical Postgres DDL lives in
  db/schema_canonical.sql and is applied by docker entry / CI.
- Table names: Postgres uses schemas (core./policy./audit./scenario.);
  SQLite uses the unqualified fallback names. This module exposes one
  helper per query site with dialect-aware SQL so graph/API code stays
  dialect-free.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import settings

BASE = Path(__file__).resolve().parents[2]
SQLITE_DDL = BASE / "db" / "schema_sqlite.sql"

_PG_PREFIX = {
    "accounts": "core.accounts",
    "transactions": "core.transactions",
    "alerts": "core.alerts",
    "graph_features": "core.graph_features",
    "policy_notes": "policy.policy_notes",
    "investigation_runs": "audit.investigation_runs",
    "human_decisions": "audit.human_decisions",
    "model_promotions": "audit.model_promotions",
    "risk_concerns": "scenario.risk_concerns",
    "scenario_sets": "scenario.scenario_sets",
    "expected_outcomes": "scenario.expected_outcomes",
    "control_runs": "scenario.control_runs",
}


def is_postgres(url: str = settings.DATABASE_URL) -> bool:
    s = url.lower()
    return s.startswith("postgres")


def _pg_dsn(url: str = settings.DATABASE_URL) -> str:
    """Strip SQLAlchemy-style driver prefix for raw psycopg."""
    return url.replace("+psycopg", "")


def t(name: str) -> str:
    """Qualified table name for the active dialect."""
    return _PG_PREFIX[name] if is_postgres() else name


def _sqlite_path(url: str = settings.DATABASE_URL) -> Path:
    # sqlite:///./data/omniguard.db  | sqlite:////abs/path | sqlite:///:memory:
    rest = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ":memory:"
    if rest in ("", ":memory:"):
        return Path(":memory:")
    p = Path(rest)
    return p if p.is_absolute() else (BASE / p)


def connect():
    if is_postgres():
        import psycopg  # deferred: only needed with Postgres

        con = psycopg.connect(_pg_dsn(settings.DATABASE_URL))
        try:
            from pgvector.psycopg import register_vector

            register_vector(con)
        except ImportError:
            pass  # embeddings fall back to plain lists; pgvector extra installs it
        return con
    path = _sqlite_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def init_db(url: str = settings.DATABASE_URL) -> None:
    """Create tables for the active dialect (idempotent)."""
    if is_postgres(url):
        ddl = (BASE / "db" / "schema_canonical.sql").read_text(encoding="utf-8")
        import psycopg

        with psycopg.connect(_pg_dsn(url)) as con:
            with con.cursor() as cur:
                try:
                    cur.execute(ddl)
                except Exception as e:
                    print(f"[db.init_db] DDL/index step skipped: {e}", flush=True)
            con.commit()
        return
    ddl = SQLITE_DDL.read_text(encoding="utf-8")
    path = _sqlite_path(url)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        try:
            con.executescript(ddl)
            con.commit()
        except sqlite3.IntegrityError:
            con.close()
            try:
                path.unlink()
            except OSError:
                pass
            con = sqlite3.connect(str(path))
            con.executescript(ddl)
            con.commit()
    finally:
        con.close()


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def loads(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    return json.loads(s)


def run(cur, sql: str, args: tuple = ()):
    """Dialect-aware execute: call sites always write `?`, converted for psycopg.

    psycopg treats bare `%` as a placeholder introducer, so literal `%`
    (e.g. LIKE patterns) is escaped first. Call sites must use `?` only —
    never native `%s`.
    """
    if is_postgres():
        sql = sql.replace("%", "%%").replace("?", "%s")
    cur.execute(sql, args)
    return cur


def fetchall(cur, sql: str, args: tuple = ()) -> list[dict]:
    run(cur, sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, list(r))) for r in cur.fetchall()]


def fetchone(cur, sql: str, args: tuple = ()) -> dict | None:
    rows = fetchall(cur, sql, args)
    return rows[0] if rows else None
