"""Resilience layer tests (offline): classifier, fallback chain, fail-fast, preflight."""
import pytest

from omniguard import llm
from omniguard.config import settings


class FakeStatus(Exception):
    def __init__(self, status_code):
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class FakeTimeout(Exception):
    pass


FakeTimeout.__name__ = "APITimeoutError"


def test_classifier():
    assert llm._classify_error(FakeStatus(429)) == "retry"
    assert llm._classify_error(FakeStatus(500)) == "retry"
    assert llm._classify_error(FakeStatus(503)) == "retry"
    assert llm._classify_error(FakeTimeout("t")) == "retry"
    assert llm._classify_error(FakeStatus(404)) == "fallback"
    assert llm._classify_error(FakeStatus(401)) == "fatal"
    assert llm._classify_error(FakeStatus(400)) == "fatal"
    assert llm._classify_error(FakeStatus(403)) == "fatal"


def _stub_stream_factory(calls, behavior):
    def fake(client, *, model, messages, idle_s, end):
        calls.append(model)
        outcome = behavior(model)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, {"input": 10, "output": 20, "total": 30}
    return fake


def test_fallback_chain_on_404(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_ensure_model_known", lambda model: None)
    good, _ = llm._mock_call("investigator", {"facts": {}, "tx_ids": [], "policy_ids": []})
    import json as _json

    calls = []
    monkeypatch.setattr(llm, "_stream_complete", _stub_stream_factory(
        calls, lambda m: FakeStatus(404) if m == settings.NIM_REASON_MODEL else _json.dumps(good)))
    parsed, tc = llm.call_json("investigator", {"facts": {}, "tx_ids": [], "policy_ids": []})
    assert calls[0] == settings.NIM_REASON_MODEL
    assert calls[-1] == settings.NIM_FALLBACK_MODEL
    assert tc["fallback"] is True
    assert tc["model_id"] == settings.NIM_FALLBACK_MODEL
    assert tc["mock"] is False
    llm._validate("investigator", parsed)


def test_fatal_401_no_retry_no_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "STRICT_LLM", True)
    monkeypatch.setattr(llm, "_ensure_model_known", lambda model: None)
    calls = []
    monkeypatch.setattr(llm, "_stream_complete", _stub_stream_factory(
        calls, lambda m: FakeStatus(401)))
    with pytest.raises(RuntimeError, match="fatal"):
        llm.call_json("challenger", {"facts": {}, "kyc": {}})
    assert len(calls) == 1  # exactly one attempt — no retry, no fallback


def test_deadline_caps_total_time(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "STRICT_LLM", True)
    monkeypatch.setattr(settings, "NIM_DEADLINE_S", 0)
    monkeypatch.setattr(llm, "_ensure_model_known", lambda model: None)
    import time as _t

    start = _t.monotonic()
    with pytest.raises(RuntimeError):
        llm.call_json("challenger", {"facts": {}, "kyc": {}})
    assert _t.monotonic() - start < 10


def test_preflight_fail_soft(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "NIM_BASE_URL", "http://127.0.0.1:9")
    llm._ensure_model_known("anything/at-all")  # must warn, never raise


class _SilentStream:
    def __iter__(self):
        import time as _t

        _t.sleep(5)
        return iter(())


def test_idle_timeout_enforced_externally():
    import time as _t

    from types import SimpleNamespace

    fake = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: _SilentStream())))
    start = _t.monotonic()
    with pytest.raises(llm._IdleTimeout):
        llm._stream_complete(fake, model="m", messages=[], idle_s=0.2,
                             end=_t.monotonic() + 30)
    assert _t.monotonic() - start < 5  # killed by idle, not by the 5s stall


def test_idle_stall_jumps_to_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_ensure_model_known", lambda model: None)
    good, _ = llm._mock_call("investigator", {"facts": {}, "tx_ids": [], "policy_ids": []})
    import json as _json

    def fake_stream(client, *, model, messages, idle_s, end):
        if model == settings.NIM_REASON_MODEL:
            raise llm._IdleTimeout("no token for Xs")
        return _json.dumps(good), {"input": 1, "output": 2, "total": 3}

    monkeypatch.setattr(llm, "_stream_complete", fake_stream)
    parsed, tc = llm.call_json("investigator", {"facts": {}, "tx_ids": [], "policy_ids": []})
    assert tc["fallback"] is True
    assert tc["model_id"] == settings.NIM_FALLBACK_MODEL
    llm._validate("investigator", parsed)
