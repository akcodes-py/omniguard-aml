"""Phase 1 gate: ENV is the only config surface, no hardcoded secrets."""
from pathlib import Path

from omniguard.config import settings

BASE = Path(__file__).resolve().parents[1]


def test_provider_surface_exists():
    for field in ("LLM_PROVIDER", "STRICT_LLM", "NIM_BASE_URL", "NIM_API_KEY",
                  "NIM_REASON_MODEL", "NIM_FAST_MODEL", "RATE_LIMIT_PER_MIN",
                  "API_KEY", "DATABASE_URL", "REDIS_URL"):
        assert hasattr(settings, field), f"missing setting {field}"
    assert settings.LLM_PROVIDER == "mock"  # safe default: zero keys, zero cost
    assert settings.NIM_BASE_URL.startswith("https://")


def test_no_hardcoded_secrets():
    compose = (BASE / "docker-compose.yml").read_text()
    assert "change-me" not in compose
    assert ":-dev-key" not in compose
    src = list((BASE / "src").rglob("*.py"))
    assert src, "no source files found"
    for f in src:
        text = f.read_text(encoding="utf-8")
        assert "change-me" not in text, f"hardcoded secret in {f.name}"
        assert "nvapi-" not in text, f"hardcoded API key in {f.name}"


def test_env_example_and_gitignore():
    example = (BASE / ".env.example").read_text()
    for key in ("LLM_PROVIDER", "NIM_API_KEY", "NIM_REASON_MODEL", "NIM_FAST_MODEL",
                "NIM_FALLBACK_MODEL", "STRICT_LLM", "POSTGRES_PASSWORD", "API_KEY"):
        assert key in example, f"{key} missing from .env.example"
    # A local .env may exist for compose; gitignore (not absence) is the enforcement.
    assert ".env" in (BASE / ".gitignore").read_text().splitlines()
