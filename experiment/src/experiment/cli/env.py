"""Environment & infrastructure checks: preflight, model, backend-check, MCP, and PyQGIS."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from experiment.services import backend_check as backend_check_service
from experiment.services import mcp_selftest as mcp_selftest_service
from experiment.services import qgis as qgis_service
from experiment.services import workflow as workflow_service

app = typer.Typer(help="Preflight checks, model pinning, MCP probes, and PyQGIS sandbox.")
_qgis_app = typer.Typer(help="PyQGIS sandbox: check availability, run scripts scrubbed.")
app.add_typer(_qgis_app, name="qgis")
console = Console(highlight=False)

RUN_ID_OPT = typer.Option(
    "", "--run-id", envvar=["EXPERIMENT_RUN_ID", "RUN_ID"], help="Run identifier"
)
MODEL_OPT = typer.Option(
    "qwen2.5:3b", "--model", envvar=["EXPERIMENT_MODEL", "MODEL"], help="Ollama model tag"
)
BACKEND_OPT = typer.Option(
    "remote-ollama",
    "--backend",
    envvar="EXPERIMENT_BACKEND",
    help="Backend profile from experiment/backends.toml",
)
SSH_HOST_OPT = typer.Option(
    None, "--ssh-host", envvar="OLLAMA_SSH_HOST", help="SSH host for ControlMaster tunnel"
)
CONTROL_PATH_OPT = typer.Option(
    None, "--control-path", envvar="OLLAMA_CONTROL_PATH", help="SSH ControlMaster socket path"
)
EXPECTED_DIGEST_OPT = typer.Option(
    None, "--expected-digest", envvar="EXPERIMENT_EXPECTED_DIGEST", help="Expected model digest"
)
OPT_MODEL_OPT = typer.Option(
    None, "--model", envvar=["EXPERIMENT_MODEL", "MODEL"], help="Optional model override"
)
HOST_OPT = typer.Option(
    None, "--host", envvar=["EXPERIMENT_HOST", "OLLAMA_HOST"], help="Optional base_url override"
)
POLL_TIMEOUT_OPT = typer.Option(
    30.0, "--poll-timeout-s", envvar="EXPERIMENT_POLL_TIMEOUT_S", help="Digest poll timeout (s)"
)
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable JSON")
SCRIPT_ARG = typer.Argument(..., help="PyQGIS script to run in the scrubbed sandbox")
ARTIFACTS_DIR_OPTION = typer.Option(Path("."), "--artifacts-dir", help="cwd for the script")
TIMEOUT_OPTION = typer.Option(120, "--timeout", help="Wall-clock timeout in seconds")

EXIT_READY = 0
EXIT_SSH_UNREACHABLE = 10
EXIT_TUNNEL_DEAD = 11
EXIT_MODEL_ABSENT = 12
EXIT_AUTH_CLIENT = 13
EXIT_TOKEN_LIMIT = 14
EXIT_COMPLETION_REJECTED = 15

_BACKEND_CHECK_EXIT_CODES: dict[str, int] = {
    "ssh-unreachable": EXIT_SSH_UNREACHABLE,
    "tunnel-dead": EXIT_TUNNEL_DEAD,
    "model-absent": EXIT_MODEL_ABSENT,
    "auth-error": EXIT_AUTH_CLIENT,
    "client-error": EXIT_AUTH_CLIENT,
    "token-limit": EXIT_TOKEN_LIMIT,
    "completion-rejected": EXIT_COMPLETION_REJECTED,
}


def backend_check_exit_code(kind: str) -> int:
    """Map a semantic :class:`BackendCheckError` kind to its CLI exit status."""
    return _BACKEND_CHECK_EXIT_CODES.get(kind, EXIT_COMPLETION_REJECTED)


@app.command()
def preflight(run_id: str = RUN_ID_OPT) -> None:
    """Validate the pilot task suite and pin the run environment."""
    try:
        rid, pins, pins_path = workflow_service.run_preflight(run_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"run_id={rid}")
    for key, value in pins.items():
        typer.echo(f"{key}={value}")
    typer.echo(f"env-pins written to {pins_path}")
    typer.echo(f"RUN_ID={rid}")


@app.command()
def model(model: str = MODEL_OPT, run_id: str = RUN_ID_OPT) -> None:
    """Start Ollama, pull the pinned model, and record its digest."""
    try:
        digest, snippet, run_dir = workflow_service.run_model(model=model, run_id=run_id)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"model={model}")
    typer.echo(f"digest={digest}")
    typer.echo(f"smoke_response={snippet}")
    typer.echo(f"artifacts written to {run_dir}")


@app.command("backend-check")
def backend_check(  # noqa: CC102
    backend: str = BACKEND_OPT,
    ssh_host: str | None = SSH_HOST_OPT,
    control_path: Path | None = CONTROL_PATH_OPT,
    expected_digest: str | None = EXPECTED_DIGEST_OPT,
    model: str | None = OPT_MODEL_OPT,
    host: str | None = HOST_OPT,
    poll_timeout_s: float = POLL_TIMEOUT_OPT,
) -> None:
    """Verify remote-ollama SSH tunnel, poll /v1/models digest, and run one tiny completion."""
    cfg = backend_check_service.BackendCheckConfig(
        backend=backend,
        ssh_host=ssh_host,
        control_path=control_path,
        expected_digest=expected_digest,
        model=model,
        host=host,
        poll_timeout_s=poll_timeout_s,
    )
    try:
        result = backend_check_service.run_backend_check(cfg)
    except backend_check_service.BackendCheckError as exc:
        typer.echo(f"ERROR [{exc.kind}]: {exc.detail}", err=True)
        typer.echo(f"HINT: {exc.hint}", err=True)
        raise typer.Exit(code=backend_check_exit_code(exc.kind)) from exc
    backend_check_service.emit_github_outputs(result)
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


@app.command("mcp-ops")
def mcp_ops(as_json: bool = JSON_OPTION) -> None:
    """List the Arm A typed GIS operation catalogue."""
    ops = mcp_selftest_service.list_operations()
    if as_json:
        payload = [{"name": name, "summary": summary} for name, summary in ops]
        typer.echo(json.dumps(payload, indent=2))
        return
    table = Table(title="Prototype GIS MCP operations", header_style="bold cyan")
    table.add_column("tool", style="green")
    table.add_column("summary")
    for name, summary in ops:
        table.add_row(name, summary)
    console.print(table)
    console.print(
        Text(
            f"{len(ops)} ops — prototype catalogue, not frozen.",
            style="dim",
        )
    )


@app.command("mcp-selftest")
def mcp_selftest(as_json: bool = JSON_OPTION) -> None:
    """Exercise the Arm A stdio MCP server against the shipped topology fixture."""
    rows = asyncio.run(mcp_selftest_service.selftest_rows())
    if as_json:
        payload = [{"step": step, "result": res, "detail": detail} for step, res, detail in rows]
        typer.echo(json.dumps(payload, indent=2))
        return
    table = Table(title="MCP stdio self-test", header_style="bold cyan")
    for col in ("step", "result", "detail"):
        table.add_column(col)
    for step, result, detail in rows:
        table.add_row(step, result, detail)
    console.print(table)


def _qgis_remediation() -> str:
    return "\n".join(
        [
            "PyQGIS is not importable from this interpreter.",
            "The sandbox is the pixi `sandbox` feature (linux-64):",
            "it ships qgis 4.2, ollama, qgis-sdk from conda-forge.",
            "",
            '  pixi run -e sandbox python -c "import qgis.core; print(qgis.core.QGIS_VERSION)"',
            "",
            "or:  pixi shell -e sandbox   then re-run `env qgis check`.",
            "In CI: ./.github/actions/setup with input environment: sandbox.",
        ]
    )


def _print_qgis_unavailable() -> None:
    console.print(
        Panel(
            Text(_qgis_remediation(), style="yellow"),
            title="PyQGIS unavailable",
            border_style="yellow",
        )
    )


@_qgis_app.command("check")
def qgis_check(as_json: bool = JSON_OPTION) -> None:
    """Report PyQGIS availability and versions; exit 3 when unavailable."""
    versions = qgis_service.qgis_versions()
    if as_json:
        typer.echo(json.dumps({"available": versions is not None, "versions": versions}, indent=2))
        if versions is None:
            raise typer.Exit(code=3)
        return
    if versions is None:
        _print_qgis_unavailable()
        raise typer.Exit(code=3)
    lines = Text()
    for key, value in versions.items():
        lines.append(f"{key:>8}  ", style="bold")
        lines.append(value + "\n")
    console.print(Panel(lines, title="PyQGIS sandbox — available", border_style="green"))


def _print_qgis_completed(completed: qgis_service.SandboxRunResult) -> None:
    console.print(
        Panel(Text(completed.stdout[-8000:] or "(no stdout)"), title="stdout", border_style="green")
    )
    if completed.stderr.strip():
        console.print(
            Panel(Text(completed.stderr[-4000:], style="red"), title="stderr", border_style="red")
        )


@_qgis_app.command("run")
def qgis_run(
    script: Path = SCRIPT_ARG,
    artifacts_dir: Path = ARTIFACTS_DIR_OPTION,
    timeout_s: int = TIMEOUT_OPTION,
) -> None:
    """Run SCRIPT with python -I and a minimal env (QT_QPA_PLATFORM=offscreen, no secrets)."""
    try:
        qgis_service.prepare_script(script, artifacts_dir)
    except qgis_service.ScriptNotFoundError:
        console.print(Text(f"missing script: {script}", style="red"))
        raise typer.Exit(code=2) from None
    except qgis_service.QgisUnavailableError:
        _print_qgis_unavailable()
        raise typer.Exit(code=3) from None
    console.print(
        Panel(
            Text(f"{script}\ncwd={artifacts_dir}\ntimeout={timeout_s}s", style="bold"),
            title="PyQGIS sandbox — running",
            border_style="blue",
        )
    )
    try:
        completed = qgis_service.run_script(script, artifacts_dir, timeout_s)
    except qgis_service.SandboxTimeoutError:
        console.print(Text(f"script timed out after {timeout_s}s", style="red"))
        raise typer.Exit(code=4) from None
    _print_qgis_completed(completed)
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)
