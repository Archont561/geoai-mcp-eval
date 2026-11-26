"""Render the Markdown digest for an experiment workflow run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tabulate import tabulate

from experiment.adapters import run_store
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.services.reports import CompletenessReport
from experiment.services.workflow import find_repo_root


def _completeness_report(harvest: Path) -> CompletenessReport | None:
    path = run_store.find_first(harvest, "summary.json")
    if path is None:
        return None
    payload = run_store.read_json_mapping(path)
    return CompletenessReport.from_mapping(payload or {})


def _header_lines(rid: str, pins: dict[str, str]) -> list[str]:
    pin_rows = [
        ("repo_sha", f"`{pins.get('repo_sha', 'n/a')}`"),
        ("pixi_lock_sha256", f"`{pins.get('pixi_lock_sha256', 'n/a')}`"),
        ("python", f"`{pins.get('python', 'n/a')}`"),
        ("ollama", f"`{pins.get('ollama', 'n/a')}`"),
        ("qgis", f"`{pins.get('qgis', 'n/a')}`"),
    ]
    table = tabulate(pin_rows, headers=("Item", "Value"), tablefmt="github")
    return [
        f"# Experiment run `{rid}`",
        "",
        "**NOT a study result** — pre-freeze scaffolding, for pipeline verification only.",
        "",
        *table.splitlines(),
        "",
        "## Where the artefacts are",
        "",
    ]


def _artifact_lines(run_url: str, rid: str) -> list[str]:
    if not run_url:
        return [f"- Local results root: `results/{rid}` (not uploaded; local run)", ""]
    return [
        f"- Run page: {run_url}",
        f"- Consolidated RunArchive artifact: `experiment-run-{rid}` "
        f"(`experiment-run-{rid}.zip` with `run.json`, JSON Schema, `summary.md`, and trials)",
        "",
    ]


def _oracle_table_lines(oracle_rows: tuple[tuple[str, str], ...]) -> list[str]:
    rows = [(f"`{cell}`", verdict) for cell, verdict in oracle_rows] or [("_none recorded_", "")]
    table = tabulate(rows, headers=("Trial", "Gate"), tablefmt="github")
    return ["### Oracle verdicts", "", *table.splitlines()]


def _what_happened_lines(report: CompletenessReport | None) -> list[str]:
    lines = ["## What happened", ""]
    if report is None:
        lines.append(
            "Preflight-only dispatch (or harvest artifact missing): no trials were "
            "expected and none were run. Re-dispatch with `stage=smoke` to exercise "
            "the pipeline end-to-end."
        )
        return lines
    label = "complete" if report.complete else "INCOMPLETE"
    lines += [
        f"- Expected trials: {len(report.expected_cells)}",
        f"- Logged trials (manifest.json lines): {len(report.logged_cells)}",
        f"- Completeness: {label}",
        "",
    ]
    if report.missing:
        lines += ["### Missing runs (never imputed)", ""]
        lines += [f"- `{cell}`" for cell in report.missing]
        lines += [""]
    lines += _oracle_table_lines(report.oracle_rows)
    return lines


def _smoke_line(model_smoke: Path) -> str:
    payload = run_store.read_json_mapping(model_smoke)
    if payload is None:
        return "- Smoke completion: unreadable"
    response = payload.get("response", "")
    return f"- Smoke completion: `{str(response).strip()[:80]}`"


def _model_lines(harvest: Path) -> list[str]:
    digest = run_store.find_first(harvest, "model-digest.txt")
    model_smoke = run_store.find_first(harvest, "model-smoke.json")
    if not digest and not model_smoke:
        return []
    lines = ["", "## Model", ""]
    if digest:
        lines.append(f"- Pin: `{run_store.read_text(digest).strip()}`")
    if model_smoke:
        lines.append(_smoke_line(model_smoke))
    return lines


def render_summary(
    harvest_dir: Path = Path("harvest"),
    run_id: str = "",
    gh: GitHubWorkflowAdapter | None = None,
) -> str:
    """Write ``<harvest_dir>/summary.md`` and append to ``$GITHUB_STEP_SUMMARY`` via adapter."""
    adapter = gh or GitHubWorkflowAdapter()
    repo_root = find_repo_root()
    harvest = harvest_dir if harvest_dir.is_absolute() else (repo_root / harvest_dir)
    rid = adapter.resolve_run_id(run_id, fallback_local=False)
    report = _completeness_report(harvest)
    lines = _header_lines(rid, run_store.read_env_pins(harvest))
    lines += _artifact_lines(adapter.run_url(), rid)
    lines += _what_happened_lines(report)
    lines += _model_lines(harvest)
    lines += [
        "",
        "## Next steps",
        "",
        "- If trials failed: inspect the per-trial artifact before re-running.",
        "- If INCOMPLETE: fix the failing trials; missing runs are never invented.",
        "- Protocol deviations must be logged in docs/study/implementation.md.",
        f"_(generated {datetime.now(UTC).isoformat()})_",
        "",
    ]
    markdown = "\n".join(lines)
    adapter.write_step_summary(markdown)
    run_store.write_text(harvest / "summary.md", markdown)
    return markdown
