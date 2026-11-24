"""Enforce rude Clean Code (CC, C901) rules strictly on production Python sources.

`rude check` treats Clean Code rules (`CC*`) as warnings and exits 0 even when
violations are found. This gate runs `rude check --format json` for `CC,C901`
against production sources and fails whenever any diagnostic is reported.
"""

from __future__ import annotations

import json
import subprocess
import sys

from tasknest import tool

PRODUCTION_ROOTS = [
    "experiment/src",
    "experiment/run_cli.py",
    "experiment-qgis-plugin/experiment_plugin",
    "tools",
]


def _parse_diagnostics(stdout: str) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        diagnostics.append(json.loads(line))
    return diagnostics


def _format_diagnostic(item: dict[str, object]) -> str:
    return (
        f"{item.get('file')}:{item.get('line')}:{item.get('column')}: "
        f"{item.get('code')} {item.get('message')}"
    )


@tool(description="Fail on any rude Clean Code (CC, C901) violation in production Python code.")
def clean_code() -> None:
    """Enforce zero Clean Code (CC, C901) diagnostics across production Python roots."""
    cmd = [
        sys.executable,
        "-m",
        "rude",
        "check",
        *PRODUCTION_ROOTS,
        "--config",
        "rude.toml",
        "--select",
        "CC,C901",
        "--format",
        "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stderr:
        sys.stderr.write(result.stderr)
    diagnostics = _parse_diagnostics(result.stdout)
    if diagnostics:
        for item in diagnostics:
            print(_format_diagnostic(item), file=sys.stderr)
        print(
            f"\nClean Code check failed: {len(diagnostics)} violation(s) found.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    print("Clean Code check passed (0 CC/C901 violations).")
