"""Central configuration — ENV is the only config surface (Phase 1).

Every tunable lives here via pydantic-settings (env-overridable, `.env`
supported). No model IDs, keys, regions, thresholds, or URLs may be
hardcoded elsewhere — enforced by tests/test_phase1_env.py.

Local defaults keep `pytest` green with zero keys. Deploy/compose uses
fail-fast (no insecure fallbacks for secrets). STRICT_LLM=true turns any
missing-key or total-LLM-outage into a loud startup/call failure instead
of silent mock.
"""
from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# MLflow 3.x blocks the filesystem tracking backend unless explicitly allowed.
# Local default URI is ./mlruns (file store), so opt in by default; a real env
# var still wins (setdefault).
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./data/omniguard.db"
    REDIS_URL: str = ""
    MLFLOW_TRACKING_URI: str = "./mlruns"

    API_KEY: str = "dev-key"  # local default only; compose requires real value

    # LLM provider: "mock" | "nim" | "bedrock"
    LLM_PROVIDER: str = "mock"
    STRICT_LLM: bool = False

    # NVIDIA NIM (OpenAI-compatible, https://integrate.api.nvidia.com/v1)
    NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NIM_API_KEY: str = ""
    NIM_REASON_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"  # Investigator, Scenario Author (primary: answers in ~2s)
    NIM_FAST_MODEL: str = "nvidia/nemotron-3.5-lightning-30b-a3b"      # Challenger, Scenario Challenger
    NIM_FALLBACK_MODEL: str = "nvidia/nemotron-3.5-lightning-30b-a3b"  # fallback if primary stalls/404s
    RATE_LIMIT_PER_MIN: int = 40
    NIM_IDLE_TIMEOUT_S: float = 30.0   # kill streamed call if no token arrives this long
    NIM_DEADLINE_S: float = 300.0      # hard cap across all attempts + fallbacks
    NIM_MAX_ATTEMPTS: int = 3          # per-model retries (retryable errors only)

    # AWS Bedrock (alternate provider)
    BEDROCK_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    EMBEDDING_DIM: int = 1024  # Titan Text Embeddings v2 default; PRD md said 1536 (OpenAI). Frozen: 1024.

    SUPERVISED_WEIGHT: float = 0.7
    ANOMALY_WEIGHT: float = 0.3
    ESCALATE_THRESHOLD: float = 0.70
    CLOSE_THRESHOLD: float = 0.30


settings = Settings()
