"""Throwaway gateway for the dashboard's browser smoke test (dashboard/e2e/).

Creates a fresh state directory, writes a test credential and a few usage reports into it, then serves
the built dashboard plus the API from that directory. Nothing touches the real operator state: every
governance path (credential, audit log, database) resolves inside --state.

    python -m scripts.e2e_gateway --state <empty dir> --port 8435
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parents[1]

SEED = [  # tier, tokens in, tokens out, agent, task reference
    ("local-small", 12000, 3000, "claude-code", "T1"),
    ("local-small", 8000, 2000, "claude-code", "T2"),
    ("cloud-premium", 4000, 1500, "aider", "T2"),
]


def prepare(state: Path) -> Path:
    if state.exists():
        shutil.rmtree(state)
    (state / ".promptwise").mkdir(parents=True)
    credential = state / ".promptwise" / "dashboard_token"
    credential.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return credential


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8435)
    args = parser.parse_args()
    state = args.state.resolve()
    credential = prepare(state)
    os.chdir(state)
    os.environ["PROMPTWISE_GATEWAY__TOKEN_PATH"] = str(credential)
    os.environ.pop("PROMPTWISE_OPERATOR_CONFIG", None)

    import uvicorn

    from core.routing.usage import record_usage
    from gateway.app import create_app
    from gateway.mcp_guard import operator_config, pinned_config

    config = pinned_config(operator_config())
    for tier, tokens_in, tokens_out, agent, task in SEED:
        record_usage(tier, tokens_in, tokens_out, agent=agent, task_ref=task, config=config, root=state)

    uvicorn.run(create_app(dashboard_dir=INSTALL_ROOT / "dashboard" / "dist"), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
