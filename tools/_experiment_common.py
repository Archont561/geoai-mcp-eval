"""Shared helpers for the experiment_* tasknest tools.

Not a tasknest task on purpose: tasknest discovery skips any path whose parts
start with `_`, so this module is never registered as a tool. It exists so the
four experiment workflow tools stop carrying byte-identical copies of the same
plumbing — one place to fix it when CI needs a change.
"""

from __future__ import annotations

import os
import time
import urllib.request
from datetime import UTC, datetime

from tasknest import ToolContext

OLLAMA_API = "http://127.0.0.1:11434"
READY_ATTEMPTS = 60
READY_SLEEP_S = 2


def resolve_run_id(run_id: str) -> str:
    if run_id:
        return run_id
    env = os.environ
    if env.get("RUN_ID"):
        return env["RUN_ID"]
    if env.get("GITHUB_RUN_ID"):
        sha = env.get("GITHUB_SHA", "local")[:8]
        return f"{env['GITHUB_RUN_ID']}-{sha}"
    return "local-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def experiment_env(ctx: ToolContext) -> dict[str, str]:
    src_roots = [
        ctx.repo_root / "experiment" / "src",
        ctx.repo_root / "experiment-qgis-plugin" / "src",
    ]
    return {"PYTHONPATH": os.pathsep.join(str(p) for p in src_roots)}


def serve_running() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_API}/api/version", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def wait_ready() -> bool:
    for _ in range(READY_ATTEMPTS):
        if serve_running():
            return True
        time.sleep(READY_SLEEP_S)
    return False
