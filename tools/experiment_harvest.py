"""Merge cell manifests, re-run the oracle gate, compute the completeness assertion."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NamedTuple

from tasknest import ToolContext, tool

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)  # tasknest execs by path; sibling helpers need tools/
from _experiment_common import (  # noqa: E402
    experiment_env,
    resolve_run_id,
)

PILOT_TASKS = ["analysis-de9im-001", "cartography-jenks-001", "prep-axis-order-001"]


def _harvest_root(ctx: ToolContext, harvest_dir: Path) -> Path:
    if harvest_dir.is_absolute():
        return harvest_dir
    return ctx.repo_root / harvest_dir


def _str_field(record: dict[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) else None


def _int_field(record: dict[str, object], key: str) -> int | None:
    value = record.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cell_key(record: dict[str, object]) -> tuple[str, str, int] | None:
    arm = _str_field(record, "arm")
    task = _str_field(record, "task")
    rep = _int_field(record, "rep")
    if arm is None or task is None or rep is None:
        return None
    return arm, task, rep


def _load_manifest(path: Path) -> tuple[tuple[str, str, int], dict[str, object]] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    key = _cell_key(record)
    return (key, record) if key is not None else None


def _manifest_records(harvest_dir: Path) -> dict[tuple[str, str, int], dict[str, object]]:
    records: dict[tuple[str, str, int], dict[str, object]] = {}
    for path in sorted(harvest_dir.rglob("manifest.json")):
        loaded = _load_manifest(path)
        if loaded is not None:
            key, record = loaded
            records[key] = record
    return records


def _find_cell_dir(harvest_dir: Path, arm: str, task: str, rep: int) -> Path | None:
    candidates = [
        harvest_dir / f"experiment-{arm}-{task}-rep{rep}",
        harvest_dir / task / arm / f"rep-{rep}",
    ]
    # download-artifact flattens into <name>/…; also accept nested layouts
    candidates.extend(harvest_dir.glob(f"experiment-{arm}-{task}-rep{rep}*"))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _write_merged_manifest(harvest_dir: Path, records: list[dict[str, object]]) -> None:
    merged = harvest_dir / "manifest.jsonl"
    merged.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )


def _expected_cells(arms: list[str], repetitions: int) -> set[tuple[str, str, int]]:
    return {
        (arm, task, rep)
        for arm in arms
        for task in PILOT_TASKS
        for rep in range(1, repetitions + 1)
    }


def _determinism_command(task: str, cell_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "experiment",
        "pilot",
        "determinism",
        task,
        "--artifacts-dir",
        str(cell_dir),
    ]


def _run_gate(
    ctx: ToolContext,
    out_dir: Path,
    cell_dir: Path,
    cell_key: tuple[str, str, int],
) -> str:
    arm, task, rep = cell_key
    try:
        result = ctx.run(
            _determinism_command(task, cell_dir),
            env=experiment_env(ctx),
            capture=True,
            check=False,
        )
    except OSError as exc:
        return f"error({exc})"
    (out_dir / f"{task}-{arm}-rep{rep}.json").write_text(
        result.stdout or result.stderr, encoding="utf-8"
    )
    return "pass" if result.returncode == 0 else f"fail(exit={result.returncode})"


def _evaluate_cell(
    ctx: ToolContext,
    out_dir: Path,
    harvest: Path,
    cell_key: tuple[str, str, int],
    skip_oracle: bool,
) -> str:
    arm, task, rep = cell_key
    if skip_oracle:
        return "skipped(smoke)"
    cell_dir = _find_cell_dir(harvest, arm, task, rep)
    if cell_dir is None:
        return "no-cell-dir"
    return _run_gate(ctx, out_dir, cell_dir, cell_key)


def _oracle_verdicts(
    ctx: ToolContext,
    harvest: Path,
    seen: set[tuple[str, str, int]],
    skip_oracle: bool,
) -> dict[str, str]:
    out_dir = harvest / "oracle"
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts: dict[str, str] = {}
    for arm, task, rep in sorted(seen):
        verdicts[f"{task}/{arm}/rep-{rep}"] = _evaluate_cell(
            ctx, out_dir, harvest, (arm, task, rep), skip_oracle
        )
    return verdicts


def _cell_label(arm: str, task: str, rep: int) -> str:
    return f"{task}/{arm}/rep-{rep}"


class _Comparison(NamedTuple):
    expected: set[tuple[str, str, int]]
    seen: set[tuple[str, str, int]]
    missing: list[tuple[str, str, int]]
    extra: list[tuple[str, str, int]]


def _comparison(arms: list[str], repetitions: int, records: dict) -> _Comparison:
    expected = _expected_cells(arms, repetitions)
    seen = set(records)
    return _Comparison(
        expected=expected,
        seen=seen,
        missing=sorted(expected - seen),
        extra=sorted(seen - expected),
    )


def _summary_dict(
    rid: str,
    comparison: _Comparison,
    oracle: dict[str, str],
) -> dict[str, object]:
    return {
        "run_id": rid,
        "expected_cells": sorted(_cell_label(a, t, r) for a, t, r in comparison.expected),
        "logged_cells": sorted(_cell_label(a, t, r) for a, t, r in comparison.seen),
        "missing": [_cell_label(a, t, r) for a, t, r in comparison.missing],
        "extra": [_cell_label(a, t, r) for a, t, r in comparison.extra],
        "oracle": oracle,
        "complete": not comparison.missing,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _raise_if_missing(missing: list[tuple[str, str, int]], fail_on_missing: bool) -> None:
    if missing and fail_on_missing:
        raise RuntimeError(
            f"completeness assertion failed: {len(missing)} missing run(s): "
            + ", ".join(_cell_label(a, t, r) for a, t, r in missing)
            + " — never invented; fix the cells and re-run"
        )


# The flat parameter list is the tasknest CLI contract; grouping would break it.
@tool(
    description="Merge cell outputs, re-run the oracle gate, list any missing runs.",
    marks=["ci", "workflow"],
)
def experiment_harvest(  # noqa: CC102
    ctx: ToolContext,
    harvest_dir: Path = Path("harvest"),
    arms: list[Literal["A", "B"]] | None = None,
    repetitions: int = 2,
    fail_on_missing: bool = True,
    skip_oracle: bool = False,
    run_id: str = "",
) -> None:
    """Merge cell outputs, re-run the oracle gate, list any missing runs."""
    arms = list(arms) if arms is not None else ["A", "B"]
    rid = resolve_run_id(run_id)
    harvest = _harvest_root(ctx, harvest_dir)
    records = _manifest_records(harvest)
    _write_merged_manifest(harvest, list(records.values()))
    comparison = _comparison(arms, repetitions, records)
    oracle = _oracle_verdicts(ctx, harvest, comparison.seen, skip_oracle)
    summary = _summary_dict(rid, comparison, oracle)
    (harvest / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    _raise_if_missing(comparison.missing, fail_on_missing)
