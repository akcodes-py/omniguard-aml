"""Policy retrieval (Graph1 Node 3): pgvector in Postgres, numpy fallback locally.

- Postgres: embedding <=> query ORDER BY cosine distance + WHERE typology_tag,
  top 3-5 current notes (effective_to IS NULL).
- SQLite/local: deterministic pseudo-embedding (sha256-seeded) + numpy cosine;
  same filter contract. Embeddings are seeded at seed.py so retrieval is stable.
- NEVER searches transactions (PRD Sec 12 refusal).
"""
from __future__ import annotations

import hashlib

import numpy as np

from .config import settings
from .db import connect, is_postgres, loads, t


def pseudo_embed(text: str, dim: int | None = None) -> list[float]:
    dim = dim or settings.EMBEDDING_DIM
    h = hashlib.sha256(text.encode()).digest()
    seed = int.from_bytes(h[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim)
    v = v / (np.linalg.norm(v) + 1e-9)
    return [float(x) for x in v]


def _cos(a: list[float], b: list[float]) -> float:
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


def retrieve(query_tags: list[str], query_text: str = "", top_k: int = 4) -> list[dict]:
    q = pseudo_embed(" ".join(query_tags) + " " + query_text)
    con = connect()
    try:
        if is_postgres():
            import json as _json

            cur = con.cursor()
            cur.execute(
                f"SELECT policy_id, version, version_hash, typology_tag, title, body, effective_to, embedding "
                f"FROM {t('policy_notes')} WHERE effective_to IS NULL"
            )
            rows = cur.fetchall()
            scored = []
            for r in rows:
                pid, ver, vh, tag, title, body, eff_to, emb = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]
                if query_tags and tag not in query_tags:
                    continue
                vec = emb.to_list() if hasattr(emb, "to_list") else list(emb) if emb is not None else pseudo_embed(body)
                scored.append((_cos(q, vec) + (0.1 if tag in query_tags else 0.0),
                               {"policy_id": pid, "version": ver, "version_hash": vh,
                                "typology_tag": tag, "title": title, "body": body[:500]}))
            scored.sort(key=lambda x: -x[0])
            return [s[1] for s in scored[:top_k]]
        cur = con.cursor()
        cur.execute("SELECT policy_id, version, version_hash, typology_tag, title, body, effective_to, embedding FROM policy_notes WHERE effective_to IS NULL")
        scored = []
        for pid, ver, vh, tag, title, body, eff_to, emb in cur.fetchall():
            if query_tags and tag not in query_tags:
                continue
            vec = loads(emb) if emb else pseudo_embed(body)
            scored.append((_cos(q, vec) + (0.1 if tag in query_tags else 0.0),
                           {"policy_id": pid, "version": ver, "version_hash": vh,
                            "typology_tag": tag, "title": title, "body": (body or "")[:500]}))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:top_k]]
    finally:
        con.close()
