"""Pre-flight check for the remote-ollama backend (SSH tunnel, digest poll, tiny completion)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tasknest import ToolContext, tool

_EXP_SRC = str(Path(__file__).resolve().parents[1] / "experiment" / "src")
if _EXP_SRC not in sys.path:
    sys.path.insert(0, _EXP_SRC)

from experiment.services import backend_check  # noqa: E402


@tool(
    description=(
        "Verify remote-ollama SSH ControlMaster tunnel, poll /v1/models for expected digest, "
        "issue one tiny completion, and exit READY with the pinned digest."
    ),
    marks=["workflow"],
)
def experiment_backend_check(  # noqa: CC102
    ctx: ToolContext,
    backend: str = "remote-ollama",
    ssh_host: str | None = None,
    control_path: str | None = None,
    expected_digest: str | None = None,
    model: str | None = None,
    host: str | None = None,
    poll_timeout_s: float = 30.0,
) -> None:
    """Thin single-@tool wrapper over experiment.services.backend_check (ADR 0006)."""
    _ = ctx
    resolved_ssh = ssh_host or os.environ.get("OLLAMA_SSH_HOST")
    resolved_ctrl = Path(control_path) if control_path else None
    cfg = backend_check.BackendCheckConfig(
        backend=backend,
        ssh_host=resolved_ssh,
        control_path=resolved_ctrl,
        expected_digest=expected_digest,
        model=model,
        host=host,
        poll_timeout_s=poll_timeout_s,
    )
    try:
        result = backend_check.run_backend_check(cfg)
    except backend_check.BackendCheckError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc
    print(
        f"{result.status} backend={result.backend} model={result.model} "
        f"digest={result.digest} base_url={result.base_url}"
    )
