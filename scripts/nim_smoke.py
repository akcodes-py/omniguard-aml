"""NIM live smoke (Phase 3): validates schemas + real usage per prompt kind.

Usage: LLM_PROVIDER=nim python scripts/nim_smoke.py
Requires NIM_API_KEY in env/.env. Prints models + token usage, never secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard import llm  # noqa: E402
from omniguard.config import settings  # noqa: E402

PAYLOADS = {
    # Challenger (30B Lightning) first: fast proof of path; investigator (552B
    # free queue) may take minutes — bounded by NIM_DEADLINE_S.
    "challenger": {"facts": {"n_txs": 4}, "kyc": {"account_purpose": "payroll", "occupation": "nurse"}},
    "investigator": {"facts": {"n_txs": 4, "total_in": 19000.0, "total_out": 18500.0,
                               "pass_through_ratio": 0.97, "velocity_24h": 4,
                               "night_ratio": 0.0, "structuring_flags": 0},
                     "tx_ids": ["tx-a", "tx-b"], "policy_ids": [["pol-x", 1]],
                     "policies": ["Rapid pass-through detection"], "memos": ["<ok>"]},
}


def main() -> None:
    assert settings.LLM_PROVIDER == "nim", "run with LLM_PROVIDER=nim"
    for kind, payload in PAYLOADS.items():
        parsed, tc = llm.call_json(kind, payload)
        llm._validate(kind, parsed)
        print(f"{kind}: model={tc['model_id']} mock={tc['mock']} "
              f"in={tc['input']} out={tc['output']} total={tc['total']}")
    print("NIM SMOKE OK")


if __name__ == "__main__":
    main()
