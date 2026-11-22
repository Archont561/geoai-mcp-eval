"""Preflight for the experiment pipeline: validate the suite, pin the environment."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from tasknest import ToolContext, tool

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)  # tasknest execs by path; sibling helpers need tools/
from _experiment_common import (  # noqa: E402
    experiment_env,
    resolve_run_id,
)


def _soft_version(ctx: ToolContext, argv: list[str]) -> str:
    try:
        result = ctx.run(argv, capture=True, check=False)
    except Exception:  # executable missing — record, don't fail preflight
        return "unavailable"
    out = (result.stdout or result.stderr).strip().splitlines()
    return out[0].strip() if out else "unavailable"


@tool(
    description="Validate the pilot task suite and pin the run environment.",
    marks=["ci", "workflow"],
)
def experiment_preflight(ctx: ToolContext, run_id: str = "") -> None:
    """Validate the pilot task suite and pin the run environment."""
    rid = resolve_run_id(run_id)
    run_dir = ctx.repo_root / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    # Gate 1: the suite must validate, or nothing downstream is meaningful.
    ctx.run(
        [sys.executable, "-m", "experiment", "pilot", "validate"],
        env=experiment_env(ctx),
    )

    lock = ctx.repo_root / "pixi.lock"
    pins = {
        "repo_sha": _soft_version(ctx, ["git", "rev-parse", "HEAD"]),
        "pixi_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
        if lock.exists()
        else "missing",
        "python": _soft_version(ctx, [sys.executable, "--version"]),
        "ollama": _soft_version(ctx, ["ollama", "--version"]),
        "qgis": _soft_version(ctx, ["qgis", "--version"]),
    }
    pins_path = run_dir / "env-pins.txt"
    pins_path.write_text("".join(f"{k}={v}\n" for k, v in pins.items()), encoding="utf-8")

    print(f"run_id={rid}")
    for key, value in pins.items():
        print(f"{key}={value}")
    print(f"env-pins written to {pins_path}")
    print(f"RUN_ID={rid}")
