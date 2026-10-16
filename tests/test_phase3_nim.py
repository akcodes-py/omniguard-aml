"""Phase 3 gate: NIM dual-routing, validation, strict failover (no live key needed)."""
import pytest

from omniguard import llm
from omniguard.config import settings


def test_model_routing():
    assert llm._model_for("investigator") == settings.NIM_REASON_MODEL
    assert llm._model_for("scenario_author") == settings.NIM_REASON_MODEL
    assert llm._model_for("challenger") == settings.NIM_FAST_MODEL
    assert llm._model_for("scenario_challenger") == settings.NIM_FAST_MODEL


def test_validate_accepts_good_rejects_bad():
    good, _ = llm._mock_call("investigator", {"facts": {}, "tx_ids": [], "policy_ids": []})
    llm._validate("investigator", good)
    with pytest.raises(ValueError):
        llm._validate("investigator", {"narrative": "missing keys"})
    with pytest.raises(ValueError):
        llm._validate("scenario_author", {"not": "a list"})
    with pytest.raises(ValueError, match="non-empty"):
        llm._validate("investigator", {**good, "matched_typology": "  "})
    with pytest.raises(ValueError, match="boolean"):
        llm._validate("challenger", {"has_verified_kyc_exoneration": "yes",
                                     "exonerating_facts": [], "cited_data_fields": []})


def test_token_total_falls_back_to_estimates(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_ensure_model_known", lambda model: None)
    good, _ = llm._mock_call("challenger", {"facts": {}, "kyc": {}})
    import json as _json

    monkeypatch.setattr(llm, "_stream_complete",
                        lambda client, **kw: (_json.dumps(good), {}))
    _, tc = llm.call_json("challenger", {"facts": {}, "kyc": {}})
    assert tc["total"] == tc["input"] + tc["output"] > 0


def test_render_embeds_payload():
    text = llm._render("challenger", {"facts": {"ptr": 0.9}, "kyc": {"occupation": "x"}})
    assert "0.9" in text and len(text) > 100


def test_nim_without_key_degrades_or_raises(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nim")
    monkeypatch.setattr(settings, "NIM_API_KEY", "")
    monkeypatch.setattr(settings, "STRICT_LLM", False)
    parsed, tc = llm.call_json("challenger", {"facts": {}, "kyc": {}})
    assert tc["mock"] is True  # loud-degrade path, schemas still hold
    llm._validate("challenger", parsed)
    monkeypatch.setattr(settings, "STRICT_LLM", True)
    with pytest.raises(RuntimeError, match="NIM_API_KEY"):
        llm.call_json("challenger", {"facts": {}, "kyc": {}})


def test_unknown_provider_rejected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm.call_json("challenger", {})

def test_token_cost_carries_latency():
    _, tc = llm._mock_call("challenger", {"facts": {}, "kyc": {}})
    assert isinstance(tc["latency_ms"], int) and tc["latency_ms"] >= 0
