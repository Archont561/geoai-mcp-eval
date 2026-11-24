"""Render the Markdown digest for an experiment workflow run."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from experiment.services.workflow import find_repo_root


def _find_one(root: Path, name: str) -> Path | None:
    matches = sorted(root.rglob(name))
    return matches[0] if matches else None


def _pins(root: Path) -> dict[str, str]:
    path = _find_one(root, "env-pins.txt")
    if path is None:
        return {}
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            pins[key.strip()] = value.strip()
    return pins


def _summary_payload(harvest: Path) -> dict[str, object]:
    path = _find_one(harvest, "summary.json")
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _oracle_rows(payload: dict[str, object]) -> list[tuple[str, str]]:
    oracle = payload.get("oracle")
    rows = oracle if isinstance(oracle, dict) else {}
    return sorted((str(k), str(v)) for k, v in rows.items())


def _run_id(run_id: str) -> str:
    env_run_id = os.environ.get("RUN_ID") or os.environ.get("GITHUB_RUN_ID")
    return run_id or env_run_id or "local"


def _run_url() -> str:
    repo_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_number = os.environ.get("GITHUB_RUN_ID", "")
    return f"{repo_url}/{repo}/actions/runs/{run_number}" if repo and run_number else ""


def _header_lines(rid: str, pins: dict[str, str]) -> list[str]:
    return [
        f"# Experiment run `{rid}`",
        "",
        "**NOT a study result** — pre-freeze scaffolding, for pipeline verification only.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| repo_sha | `{pins.get('repo_sha', 'n/a')}` |",
        f"| pixi_lock_sha256 | `{pins.get('pixi_lock_sha256', 'n/a')}` |",
        f"| python | `{pins.get('python', 'n/a')}` |",
        f"| ollama | `{pins.get('ollama', 'n/a')}` |",
        f"| qgis | `{pins.get('qgis', 'n/a')}` |",
        "",
        "## Where the artefacts are",
        "",
    ]


def _artifact_lines(run_url: str, rid: str) -> list[str]:
    if not run_url:
        return [f"- Local results root: `results/{rid}` (not uploaded; local run)", ""]
    return [
        f"- Run page: {run_url}",
        f"- Merged results artifact: `experiment-results-{rid}`",
        "- Per-cell artifacts: `experiment-<arm>-<task>-rep<n>`",
        f"- Summary artifact: `experiment-summary-{rid}`",
        "",
    ]


def _oracle_table_lines(oracle_rows: list[tuple[str, str]]) -> list[str]:
    lines = ["### Oracle verdicts", "", "| Cell | Gate |", "|---|---|"]
    if oracle_rows:
        lines += [f"| `{cell}` | {verdict} |" for cell, verdict in oracle_rows]
    else:
        lines += ["| _none recorded_ | |"]
    return lines


def _what_happened_lines(
    completeness: dict[str, object], oracle_rows: list[tuple[str, str]]
) -> list[str]:
    lines = ["## What happened", ""]
    if not completeness:
        lines.append(
            "Preflight-only dispatch (or harvest artifact missing): no cells were "
            "expected and none were run. Re-dispatch with `stage=smoke` to exercise "
            "the pipeline end-to-end."
        )
        return lines
    missing = list(completeness.get("missing", []))  # type: ignore[arg-type]
    logged = list(completeness.get("logged_cells", []))  # type: ignore[arg-type]
    expected = list(completeness.get("expected_cells", []))  # type: ignore[arg-type]
    label = "complete" if completeness.get("complete") else "INCOMPLETE"
    lines += [
        f"- Expected cells: {len(expected)}",
        f"- Logged cells (manifest.json lines): {len(logged)}",
        f"- Completeness: {label}",
        "",
    ]
    if missing:
        lines += ["### Missing runs (never imputed)", ""]
        lines += [f"- `{cell}`" for cell in missing]
        lines += [""]
    lines += _oracle_table_lines(oracle_rows)
    return lines


def _smoke_line(model_smoke: Path) -> str:
    try:
        payload = json.loads(model_smoke.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "- Smoke completion: unreadable"
    response = payload.get("response", "") if isinstance(payload, dict) else ""
    return f"- Smoke completion: `{str(response).strip()[:80]}`"


def _model_lines(harvest: Path) -> list[str]:
    digest = _find_one(harvest, "model-digest.txt")
    model_smoke = _find_one(harvest, "model-smoke.json")
    if not digest and not model_smoke:
        return []
    lines = ["", "## Model", ""]
    if digest:
        lines.append(f"- Pin: `{digest.read_text(encoding='utf-8').strip()}`")
    if model_smoke:
        lines.append(_smoke_line(model_smoke))
    return lines


def render_summary(harvest_dir: Path = Path("harvest"), run_id: str = "") -> str:
    """Write ``<harvest_dir>/summary.md`` (and append to ``$GITHUB_STEP_SUMMARY`` if set)."""
    repo_root = find_repo_root()
    harvest = harvest_dir if harvest_dir.is_absolute() else (repo_root / harvest_dir)
    rid = _run_id(run_id)
    payload = _summary_payload(harvest)
    lines = _header_lines(rid, _pins(harvest))
    lines += _artifact_lines(_run_url(), rid)
    lines += _what_happened_lines(payload, _oracle_rows(payload))
    lines += _model_lines(harvest)
    lines += [
        "",
        "## Next steps",
        "",
        "- If cells failed: inspect the per-cell artifact before re-running.",
        "- If INCOMPLETE: fix the failing cells; missing runs are never invented.",
        "- Protocol deviations must be logged in docs/study/implementation.md.",
        f"_(generated {datetime.now(UTC).isoformat()})_",
        "",
    ]
    markdown = "\n".join(lines)
    summary_target = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_target:
        with open(summary_target, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    harvest.mkdir(parents=True, exist_ok=True)
    (harvest / "summary.md").write_text(markdown, encoding="utf-8")
    return markdown
