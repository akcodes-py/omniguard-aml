"""LLM access: mock | NVIDIA NIM | Bedrock, with strict JSON + throttling.

Routing (dual-model):
- investigator, scenario_author -> NIM_REASON_MODEL (DeepSeek-V4.1-Flash)
- challenger, scenario_challenger -> NIM_FAST_MODEL (Nemotron 3.5 Lightning)
- provider "bedrock" keeps the legacy Claude path; "mock" (default) is the
  deterministic offline stand-in with identical JSON schemas.

Rules: temperature 0, response_format json_object on NIM, schema validation,
repair retry, 429/5xx exponential backoff, per-provider pacing Honouring
RATE_LIMIT_PER_MIN. STRICT_LLM=true turns any live failure into a loud
RuntimeError (never silent mock); otherwise failures degrade to mock with
an stderr warning and mock:true in token_cost.
"""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from collections import defaultdict
from typing import Any

from .config import settings
from .prompts import TEMPLATES, prompt_version_hash

REASON_KINDS = ("investigator", "scenario_author")

REQUIRED_KEYS = {
    "investigator": ("matched_typology", "cited_tx_ids", "cited_policy_ids", "narrative"),
    "challenger": ("has_verified_kyc_exoneration", "exonerating_facts", "cited_data_fields"),
}


def _mock_investigator(payload: dict) -> dict:
    facts = payload.get("facts", {})
    txs = payload.get("tx_ids", [])
    ptr = float(facts.get("pass_through_ratio", 0) or 0)
    struct = int(facts.get("structuring_flags", 0) or 0)
    typo = "benign"
    if ptr > 0.8 and facts.get("n_txs", 0) >= 3:
        typo = "rapid_pass_through"
    elif struct > 0:
        typo = "structuring"
    elif float(facts.get("night_ratio", 0) or 0) > 0.5:
        typo = "layering"
    return {
        "matched_typology": typo,
        "cited_tx_ids": txs[:3],
        "cited_policy_ids": payload.get("policy_ids", [])[:2],
        "numeric_claims": {
            "total_in": facts.get("total_in", 0.0),
            "total_out": facts.get("total_out", 0.0),
        },
        "narrative": f"mock investigator: {typo} (ptr={ptr}, struct={struct})",
    }


def _mock_challenger(payload: dict) -> dict:
    kyc = payload.get("kyc", {})
    purpose = (kyc.get("account_purpose") or "").lower()
    occupation = (kyc.get("occupation") or kyc.get("occupation_category") or "")
    if purpose in ("payroll", "treasury", "merchant settlement", "personal") and occupation:
        return {
            "has_verified_kyc_exoneration": True,
            "exonerating_facts": [f"account_purpose={purpose}", f"occupation={occupation}"],
            "cited_data_fields": ["account_purpose", "occupation"],
        }
    return {"has_verified_kyc_exoneration": False, "exonerating_facts": [], "cited_data_fields": []}


def _mock_scenario_author(payload: dict) -> Any:
    concern = str(payload.get("concern", "general risk"))[:80]
    return [
        {"kind": "suspicious", "typology": "split_layering", "n_txs": 5, "amount_each": 9500.0,
         "window_hours": 48.0, "backstory": concern, "expected": "ALERT"},
        {"kind": "suspicious", "typology": "staggered_timing", "n_txs": 4, "amount_each": 4800.0,
         "window_hours": 72.0, "backstory": concern, "expected": "ALERT"},
        {"kind": "benign", "typology": "treasury_sweep", "n_txs": 3, "amount_each": 9500.0,
         "window_hours": 24.0, "backstory": "routine treasury consolidation", "expected": "NO_ALERT"},
        {"kind": "benign", "typology": "payroll", "n_txs": 6, "amount_each": 3200.0,
         "window_hours": 12.0, "backstory": "monthly payroll run", "expected": "NO_ALERT"},
    ]


def _mock_scenario_challenger(payload: dict) -> Any:
    out = []
    for i, s in enumerate(payload.get("scenarios", [])):
        leakage = "memo contains payout label" if s.get("kind") == "benign" else "none found"
        out.append({"scenario_idx": i, "label_flip_arg": "opposite outcome arguable",
                    "leakage": leakage, "consistency": "amounts match backstory",
                    "verdict": "KEEP"})
    return out


MOCKS = {"investigator": _mock_investigator, "challenger": _mock_challenger,
         "scenario_author": _mock_scenario_author, "scenario_challenger": _mock_scenario_challenger}


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, default=str)) // 4)


def _mock_call(kind: str, payload: dict) -> tuple[Any, dict]:
    if kind not in MOCKS:
        raise ValueError(f"unknown prompt kind: {kind}")
    t0 = time.monotonic()
    parsed = MOCKS[kind](payload)
    json.dumps(parsed)  # strict-JSON check
    tc = {"input": _estimate_tokens(payload), "output": _estimate_tokens(parsed),
          "total": _estimate_tokens(payload) + _estimate_tokens(parsed),
          "model_id": "mock://" + kind, "mock": True,
          "latency_ms": int((time.monotonic() - t0) * 1000),
          "prompt_version_hash": prompt_version_hash()}
    return parsed, tc


# ---------------------------------------------------------------- live paths

_pace_lock = threading.Lock()
_last_call: dict[str, float] = {}


def _pace(provider: str) -> None:
    """Enforce RATE_LIMIT_PER_MIN spacing per provider (thread-safe)."""
    interval = 60.0 / max(settings.RATE_LIMIT_PER_MIN, 1)
    with _pace_lock:
        wait = _last_call.get(provider, 0.0) + interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    with _pace_lock:
        _last_call[provider] = time.monotonic()


def _render(kind: str, payload: dict) -> str:
    brief = {k: json.dumps(v, default=str)[:6000] for k, v in payload.items()}
    return TEMPLATES[kind].format_map(defaultdict(str, brief))


def _validate(kind: str, parsed: Any) -> None:
    if kind in ("scenario_author", "scenario_challenger"):
        if not isinstance(parsed, list):
            raise ValueError(f"{kind} must return a JSON list")
        return
    if not isinstance(parsed, dict):
        raise ValueError(f"{kind} must return a JSON object")
    missing = [k for k in REQUIRED_KEYS[kind] if k not in parsed]
    if missing:
        raise ValueError(f"{kind} missing keys: {missing}")
    if kind == "investigator" and not str(parsed.get("matched_typology") or "").strip():
        raise ValueError("investigator matched_typology must be a non-empty string")
    if kind == "challenger" and not isinstance(parsed.get("has_verified_kyc_exoneration"), bool):
        raise ValueError("challenger has_verified_kyc_exoneration must be a boolean")


def _model_for(kind: str) -> str:
    return settings.NIM_REASON_MODEL if kind in REASON_KINDS else settings.NIM_FAST_MODEL


class _IdleTimeout(TimeoutError):
    """No token arrived within the idle window — the call is stuck, not slow."""


class _DeadlineExceeded(TimeoutError):
    """Shared retry budget exhausted."""


_RETRY_NAMES = {"APITimeoutError", "APIConnectionError", "TimeoutError",
                "ConnectError", "ReadTimeout", "_IdleTimeout", "_DeadlineExceeded"}


def _classify_error(e: Exception) -> str:
    """Return 'retry' | 'fallback' | 'fatal'.

    - retry: timeouts, idle stalls, 429, 5xx, unknown connection errors.
    - fallback: 404 (wrong/missing model id) — try the next model in chain.
    - fatal: 401/400/403/422 — retrying or falling back cannot help.
    """
    if type(e).__name__ in _RETRY_NAMES:
        return "retry"
    status = getattr(e, "status_code", None)
    if status is None:
        return "retry"
    if status == 404:
        return "fallback"
    if status == 429 or status == 408 or (isinstance(status, int) and status >= 500):
        return "retry"
    return "fatal"


def _backoff(attempt: int) -> float:
    return min(2 ** attempt + random.uniform(0, 1), 15.0)


_CATALOG: dict[str, set[str]] = {}


def _ensure_model_known(model: str) -> None:
    """Preflight: verify the model id against the NIM catalog (cached, fail-soft)."""
    if settings.LLM_PROVIDER != "nim" or not settings.NIM_API_KEY:
        return
    base = settings.NIM_BASE_URL
    if base not in _CATALOG:
        try:
            from openai import OpenAI

            client = OpenAI(base_url=base, api_key=settings.NIM_API_KEY, timeout=15.0)
            _CATALOG[base] = {m.id for m in client.models.list().data}
        except Exception as e:  # noqa: BLE001 — catalog down must not block inference
            print(f"WARNING: NIM preflight unreachable ({e}); continuing", file=sys.stderr)
            return
    if model not in _CATALOG[base]:
        print(f"WARNING: model {model} not in NIM catalog; call may 404", file=sys.stderr)


def _stream_complete(client, *, model: str, messages: list[dict],
                     idle_s: float, end: float) -> tuple[str, dict]:
    """Stream a chat completion with EXTERNAL idle enforcement.

    The blocking network read runs on a pump thread; the main thread drains
    a queue with q.get(timeout=idle_s). Silence of any kind — no chunks, only
    SSE keep-alives swallowed by the parser, a wedged socket — raises
    _IdleTimeout. Slowness with progressing tokens is never killed.
    Returns (text, usage). Raises _IdleTimeout, _DeadlineExceeded, or the
    underlying API error.
    """
    import queue as _queue

    q: _queue.Queue = _queue.Queue()

    def _pump() -> None:
        try:
            stream = client.chat.completions.create(
                model=model, messages=messages,
                response_format={"type": "json_object"},
                temperature=0, max_tokens=2000, stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                q.put(("chunk", chunk))
            q.put(("done", None))
        except Exception as e:  # noqa: BLE001
            q.put(("error", e))

    threading.Thread(target=_pump, daemon=True).start()
    acc: list[str] = []
    usage: dict = {}
    while True:
        if time.monotonic() > end:
            raise _DeadlineExceeded(f"shared {settings.NIM_DEADLINE_S}s budget exhausted")
        try:
            kind, payload = q.get(timeout=min(idle_s, max(1.0, end - time.monotonic())))
        except Exception:
            raise _IdleTimeout(f"no token for {idle_s}s from {model}") from None
        if kind == "done":
            return "".join(acc), usage
        if kind == "error":
            raise payload
        chunk = payload
        delta = chunk.choices[0].delta if chunk.choices else None
        piece = getattr(delta, "content", None) if delta else None
        if piece:
            acc.append(piece)
        u = getattr(chunk, "usage", None)
        if u is not None:
            usage = {"input": getattr(u, "prompt_tokens", 0) or 0,
                     "output": getattr(u, "completion_tokens", 0) or 0,
                     "total": getattr(u, "total_tokens", 0) or 0}


def _chain_for(kind: str) -> list[str]:
    """Primary model first, 70B fallback for the reasoning kinds (audit-logged).

    Investigator and challenger currently share the Lightning brain (free-tier
    pragmatism — 552B is unservable). Independence loss is limited: the
    challenger is evidence-gated (rule check on DB fields), not open reasoning.
    """
    primary = _model_for(kind)
    if kind in REASON_KINDS and settings.NIM_FALLBACK_MODEL != primary:
        return [primary, settings.NIM_FALLBACK_MODEL]
    return [primary]


def _nim_call(kind: str, payload: dict) -> tuple[Any, dict]:
    if not settings.NIM_API_KEY:
        raise RuntimeError("NIM_API_KEY missing — set it in .env (free key at build.nvidia.com)")
    from openai import OpenAI

    attempts = settings.NIM_MAX_ATTEMPTS
    idle_s = settings.NIM_IDLE_TIMEOUT_S
    end = time.monotonic() + settings.NIM_DEADLINE_S
    system = ("You are a precise compliance assistant. Return ONLY a valid JSON value "
              "matching the requested schema. No prose, no markdown fences, no arithmetic.")
    content = _render(kind, payload)
    client = OpenAI(base_url=settings.NIM_BASE_URL, api_key=settings.NIM_API_KEY, timeout=120.0)
    base_client = client
    tried = 0
    last_err: Exception | None = None
    t_start = time.monotonic()
    for model in _chain_for(kind):
        _ensure_model_known(model)
        for _ in range(attempts):
            if time.monotonic() > end:
                break
            tried += 1
            _pace("nim")
            print(f"[nim] attempt {tried} model={model} "
                  f"remaining={max(0.0, end - time.monotonic()):.0f}s",
                  file=sys.stderr, flush=True)
            try:
                # Per-attempt network cap always fits inside the remaining
                # shared budget — a stalled attempt can never eat the whole
                # deadline (the bug that hung the first smoke).
                remaining = max(15.0, end - time.monotonic())
                call_client = base_client.with_options(timeout=min(120.0, remaining))
                text, usage = _stream_complete(
                    call_client, model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": content}],
                    idle_s=idle_s, end=end)
                try:
                    parsed = json.loads(text.strip())
                except json.JSONDecodeError as e:
                    last_err = e
                    content += "\nYour previous reply was not valid JSON. Reply with ONLY the JSON value."
                    continue
                try:
                    _validate(kind, parsed)
                except ValueError as e:
                    last_err = e
                    content += f"\nYour previous reply failed validation ({e}). Reply with ONLY corrected JSON."
                    continue
                u_in = usage.get("input") or _estimate_tokens(payload)
                u_out = usage.get("output") or _estimate_tokens(parsed)
                tc = {"input": u_in,
                      "output": u_out,
                      "total": usage.get("total") or (u_in + u_out),
                      "model_id": model, "mock": False,
                      "fallback": model != _model_for(kind),
                      "attempts": tried,
                      "latency_ms": int((time.monotonic() - t_start) * 1000),
                      "prompt_version_hash": prompt_version_hash()}
                return parsed, tc
            except Exception as e:  # noqa: BLE001
                verdict = _classify_error(e)
                last_err = e
                print(f"[nim] attempt {tried} {type(e).__name__} -> {verdict}",
                      file=sys.stderr, flush=True)
                if verdict == "fatal":
                    raise RuntimeError(f"NIM call fatal ({model}): {e}") from e
                if verdict == "fallback":
                    print(f"WARNING: {model} not found; falling back in chain", file=sys.stderr)
                    break  # next model in chain — no point retrying a wrong id
                if isinstance(e, _IdleTimeout) and model != _chain_for(kind)[-1]:
                    # Requeueing a stalled free-tier request loses queue position;
                    # go straight to the fallback model instead of retrying.
                    # (On the last model in chain, fall through to normal retry.)
                    print(f"WARNING: {model} stalled; falling back in chain", file=sys.stderr)
                    break
                time.sleep(_backoff(tried))
        if time.monotonic() > end:
            break
    raise RuntimeError(f"NIM call failed after {tried} attempts ({_model_for(kind)}): {last_err}")


def _bedrock_call(kind: str, payload: dict) -> tuple[Any, dict]:
    import boto3

    t0 = time.monotonic()
    br = boto3.client("bedrock-runtime", region_name=settings.BEDROCK_REGION)
    body = json.dumps({"anthropic_version": "bedrock-2023-05-31",
                       "max_tokens": 1000,
                       "messages": [{"role": "user", "content": json.dumps(payload, default=str)}]})
    resp = br.invoke_model(modelId=settings.BEDROCK_MODEL_ID, body=body)
    data = json.loads(resp["body"].read())
    text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
    parsed = json.loads(text)
    _validate(kind, parsed)
    return parsed, {"input": _estimate_tokens(payload), "output": _estimate_tokens(parsed),
                    "total": _estimate_tokens(payload) + _estimate_tokens(parsed),
                    "model_id": settings.BEDROCK_MODEL_ID,
                    "mock": False, "prompt_version_hash": prompt_version_hash(),
                    "latency_ms": int((time.monotonic() - t0) * 1000)}


def call_json(kind: str, payload: dict) -> tuple[Any, dict]:
    """Returns (parsed_json, token_cost). Live failures: STRICT_LLM raises, else mock."""
    provider = settings.LLM_PROVIDER
    if provider == "nim":
        try:
            return _nim_call(kind, payload)
        except Exception as e:  # noqa: BLE001
            if settings.STRICT_LLM:
                raise
            print(f"WARNING: NIM failed ({e}); degrading to mock", file=sys.stderr)
    elif provider == "bedrock":
        try:
            return _bedrock_call(kind, payload)
        except Exception as e:  # noqa: BLE001
            if settings.STRICT_LLM:
                raise
            print(f"WARNING: Bedrock failed ({e}); degrading to mock", file=sys.stderr)
    elif provider != "mock":
        raise ValueError(f"unknown LLM_PROVIDER: {provider}")
    return _mock_call(kind, payload)
