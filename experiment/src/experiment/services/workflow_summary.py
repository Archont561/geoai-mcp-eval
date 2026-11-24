"""Render the Markdown digest for an experiment workflow run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from experiment.adapters import run_store
from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.services.workflow import find_repo_root


def _summary_payload(harvest: Path) -> dict[str, object]:
    path = run_store.find_first(harvest, "summary.json")
    if path is None:
        return {}
    return run_store.read_json_mapping(path) or {}


def _oracle_rows(payload: dict[str, object]) -> list[tuple[str, str]]:
    oracle = payload.get("oracle")
    rows = oracle if isinstance(oracle, dict) else {}
    return sorted((str(k), str(v)) for k, v in rows.items())


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
    payload = _summary_payload(harvest)
    lines = _header_lines(rid, run_store.read_env_pins(harvest))
    lines += _artifact_lines(adapter.run_url(), rid)
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
    adapter.write_step_summary(markdown)
    run_store.write_text(harvest / "summary.md", markdown)
    return markdown
