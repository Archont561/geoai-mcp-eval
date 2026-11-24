"""Non-destructive post-session review for human-baseline takes.

Pure Python with no QGIS, Qt, or qgis-sdk imports. Reads an immutable completed
``session-<ts>/`` directory (``human-reference-record.json`` + ``events.jsonl``),
merges any audited manual action groups and optional QGIS ``processing.log``
executions, and atomically writes separate derived artifacts:

- ``human-reference-record.reviewed.json``
- ``human_trajectory.jsonl``

Raw evidence files (``events.jsonl``, ``human-reference-record.json``, outputs,
and task YAMLs) are never modified.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment_plugin import _io, metrics, session

REVIEWED_RECORD_FILENAME = "human-reference-record.reviewed.json"
TRAJECTORY_FILENAME = "human_trajectory.jsonl"
_PROCESSING_CALL_NAMES = {"run", "runAndLoadResults"}


class ReviewError(Exception):
    """Raised when a session take cannot be reviewed honestly."""


@dataclass(frozen=True)
class ReviewActionInput:
    """One audited manual GIS action group supplied during post-session review."""

    action_group: str
    tool: str | None = None
    ts: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    """Artifacts and structured payloads produced by a post-session review."""

    reviewed_record_path: Path
    trajectory_path: Path
    record: dict[str, Any]
    trajectory_entries: list[dict[str, Any]]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ast_to_jsonable(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _ast_to_jsonable(node.operand)
        if isinstance(operand, (int, float)):
            return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.Dict):
        return {
            str(_ast_to_jsonable(k)): _ast_to_jsonable(v)
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        }
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_ast_to_jsonable(elt) for elt in node.elts]
    return ast.unparse(node)


def _parse_params_mapping(raw_expr: str) -> dict[str, Any] | None:
    tree = ast.parse(raw_expr.strip(), mode="eval")
    value = _ast_to_jsonable(tree.body)
    if not isinstance(value, Mapping):
        raise ValueError("parameters expression did not evaluate to a mapping")
    return metrics.sanitize_parameters(value)


def _parse_processing_call(payload: str) -> tuple[str, dict[str, Any] | None]:
    tree = ast.parse(payload.strip(), mode="eval")
    call = tree.body
    if not isinstance(call, ast.Call):
        raise ValueError("expected processing.run(...) call")
    func_name = call.func.attr if isinstance(call.func, ast.Attribute) else None
    if func_name not in _PROCESSING_CALL_NAMES or not call.args:
        raise ValueError("unsupported processing call form")
    alg_id = _ast_to_jsonable(call.args[0])
    if not isinstance(alg_id, str) or not alg_id.strip():
        raise ValueError("missing algorithm_id string")
    params: dict[str, Any] | None = None
    if len(call.args) >= 2:
        raw_params = _ast_to_jsonable(call.args[1])
        if not isinstance(raw_params, Mapping):
            raise ValueError("second argument is not a parameter mapping")
        params = metrics.sanitize_parameters(raw_params)
    return alg_id.strip(), params


def _parse_algorithm_line(line: str) -> metrics.ProcessingExecution:
    parts = line.split("|", 2)
    if len(parts) < 3:
        raise ValueError("expected ALGORITHM|<timestamp>|<payload>")
    raw_ts = parts[1].strip()
    ts = raw_ts.replace(" ", "T", 1) if " " in raw_ts else raw_ts
    payload = parts[2].strip()
    if payload.startswith("processing."):
        alg_id, params = _parse_processing_call(payload)
    elif "|" in payload:
        alg_part, params_part = payload.split("|", 1)
        alg_id = alg_part.strip()
        if not alg_id:
            raise ValueError("empty algorithm_id")
        params = _parse_params_mapping(params_part) if params_part.strip() else None
    else:
        raise ValueError("unrecognized ALGORITHM payload")
    return metrics.ProcessingExecution(
        ts=ts or "",
        algorithm_id=alg_id,
        parameters=params,
        entry_timestamp=ts or None,
    )


def parse_processing_log(
    log_path: str | Path,
) -> tuple[list[metrics.ProcessingExecution], list[str]]:
    """Parse QGIS ``processing.log`` ``ALGORITHM|...`` lines without executing code."""
    path = Path(log_path).expanduser().resolve()
    if not path.is_file():
        raise ReviewError(f"processing log does not exist: {path}")
    executions: list[metrics.ProcessingExecution] = []
    errors: list[str] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith("ALGORITHM|"):
            continue
        try:
            executions.append(_parse_algorithm_line(line))
        except Exception as exc:
            errors.append(f"line {lineno}: {exc}")
    return executions, errors


def _validate_session_dir(session_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    if not session_dir.is_dir():
        raise ReviewError(f"session directory does not exist: {session_dir}")
    if (session_dir / "session-abandoned.json").exists():
        raise ReviewError(f"cannot review abandoned session: {session_dir}")
    record_path = session_dir / "human-reference-record.json"
    if not record_path.is_file():
        raise ReviewError(f"missing human-reference-record.json in {session_dir}")
    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        raise ReviewError(f"missing events.jsonl in {session_dir}")
    try:
        raw_record = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReviewError(f"unreadable human-reference-record.json: {exc}") from exc
    if not isinstance(raw_record, dict):
        raise ReviewError("human-reference-record.json must contain a JSON object")
    if raw_record.get("record_version") != session.RECORD_VERSION:
        raise ReviewError(
            f"unsupported record_version={raw_record.get('record_version')!r} "
            f"(expected {session.RECORD_VERSION})"
        )
    if raw_record.get("status") != "recorded":
        raise ReviewError(f"session status is {raw_record.get('status')!r}, expected 'recorded'")
    return record_path, events_path, raw_record


def _normalize_manual_inputs(
    items: Sequence[ReviewActionInput | Mapping[str, Any]], default_ts: str
) -> list[metrics.ManualActionGroup]:
    normalized: list[metrics.ManualActionGroup] = []
    for item in items:
        if isinstance(item, ReviewActionInput):
            raw_group, raw_tool, raw_ts = item.action_group, item.tool, item.ts
        elif isinstance(item, Mapping):
            raw_group = item.get("action_group", "")
            raw_tool = item.get("tool")
            raw_ts = item.get("ts")
        else:
            raise ValueError("manual_actions entries must be ReviewActionInput or mapping")
        clean_group = _clean_text(raw_group)
        if not clean_group:
            raise ValueError("action_group must be non-empty")
        normalized.append(
            metrics.ManualActionGroup(
                ts=_clean_text(raw_ts) or default_ts,
                action_group=clean_group,
                tool=_clean_text(raw_tool),
            )
        )
    return normalized


def _execution_dedup_key(item: metrics.ProcessingExecution) -> tuple[str, str, str]:
    params_key = json.dumps(item.parameters, sort_keys=True) if item.parameters is not None else ""
    ts_prefix = (item.entry_timestamp or item.ts or "").replace(" ", "T", 1)[:19]
    return (item.algorithm_id, params_key, ts_prefix)


def _load_recorded_executions(
    raw_study: Mapping[str, Any],
) -> list[tuple[metrics.ProcessingExecution, str]]:
    items: list[tuple[metrics.ProcessingExecution, str]] = []
    for raw in raw_study.get("processing_executions") or []:
        if not isinstance(raw, Mapping) or not raw.get("algorithm_id"):
            continue
        execution = metrics.ProcessingExecution(
            ts=str(raw.get("ts") or ""),
            algorithm_id=str(raw["algorithm_id"]),
            parameters=metrics.sanitize_parameters(raw.get("parameters")),
            history_entry_id=raw.get("history_entry_id"),
            entry_timestamp=_clean_text(raw.get("entry_timestamp")),
        )
        items.append((execution, "host:processing"))
    return items


def _load_recorded_manual_groups(
    raw_study: Mapping[str, Any],
) -> list[tuple[metrics.ManualActionGroup, str]]:
    items: list[tuple[metrics.ManualActionGroup, str]] = []
    for raw in raw_study.get("manual_action_groups") or []:
        if not isinstance(raw, Mapping) or not _clean_text(raw.get("action_group")):
            continue
        group = metrics.ManualActionGroup(
            ts=str(raw.get("ts") or ""),
            action_group=str(raw["action_group"]).strip(),
            tool=_clean_text(raw.get("tool")),
        )
        items.append((group, "session_manual"))
    return items


def _build_trajectory(
    executions: Sequence[tuple[metrics.ProcessingExecution, str]],
    manual_groups: Sequence[tuple[metrics.ManualActionGroup, str]],
) -> list[dict[str, Any]]:
    raw_entries: list[tuple[str, int, dict[str, Any]]] = []
    order = 0
    for item, origin in executions:
        entry = item.to_dict()
        entry["kind"] = "processing_execution"
        entry["origin"] = origin
        sort_ts = item.entry_timestamp or item.ts or ""
        raw_entries.append((sort_ts, order, entry))
        order += 1
    for group, origin in manual_groups:
        entry = group.to_dict()
        entry["kind"] = "manual_action_group"
        entry["origin"] = origin
        raw_entries.append((group.ts or "", order, entry))
        order += 1
    raw_entries.sort(key=lambda row: (row[0], row[1]))
    trajectory: list[dict[str, Any]] = []
    for seq, (_, _, entry) in enumerate(raw_entries, start=1):
        ordered = {"seq": seq, **entry}
        trajectory.append(ordered)
    return trajectory


def review_session(
    session_dir: str | Path,
    *,
    manual_actions: Sequence[ReviewActionInput | Mapping[str, Any]] = (),
    mark_reviewed: bool = False,
    reviewer: str | None = None,
    notes: str | None = None,
    processing_log: str | Path | None = None,
    output_dir: str | Path | None = None,
    reviewed_at: datetime | None = None,
) -> ReviewResult:
    """Audit a completed session take and emit separate reviewed artifacts."""
    source_dir = Path(session_dir).expanduser().resolve()
    record_path, events_path, raw_record = _validate_session_dir(source_dir)
    reviewed_ts = (reviewed_at or datetime.now(UTC)).isoformat()
    added_manual = _normalize_manual_inputs(manual_actions, default_ts=reviewed_ts)

    raw_study = raw_record.get("study_metrics")
    if not isinstance(raw_study, Mapping):
        raise ReviewError("human-reference-record.json is missing study_metrics")

    executions = _load_recorded_executions(raw_study)
    seen_keys = {_execution_dedup_key(item) for item, _ in executions}
    log_path: Path | None = None
    log_sha256: str | None = None
    log_errors: list[str] = []
    if processing_log is not None and _clean_text(processing_log):
        log_path = Path(processing_log).expanduser().resolve()
        parsed_log, log_errors = parse_processing_log(log_path)
        log_sha256 = session.sha256_file(log_path)
        for item in parsed_log:
            key = _execution_dedup_key(item)
            if key not in seen_keys:
                seen_keys.add(key)
                executions.append((item, "processing_log"))

    manual_groups = _load_recorded_manual_groups(raw_study)
    manual_groups.extend((group, "post_session_review") for group in added_manual)

    raw_pending = list(raw_study.get("pending_reasons") or [])
    processing_connected = bool(raw_study.get("processing_hook_connected")) or (
        log_path is not None
    )
    processing_incomplete = (
        bool(log_errors)
        if log_path is not None
        else ("processing_history_incomplete" in raw_pending)
    )

    state = metrics.SessionMetricsState(
        processing_hook_connected=processing_connected,
        processing_history_incomplete=processing_incomplete,
        processing_executions=[item for item, _ in executions],
        manual_action_groups=[group for group, _ in manual_groups],
    )
    steps, tools, metrics_status, study_metrics = state.build_summary(
        manual_review_complete=mark_reviewed
    )

    reviewed_record = copy.deepcopy(raw_record)
    reviewed_record["session"]["steps"] = steps
    reviewed_record["session"]["tools"] = tools
    reviewed_record["session"]["metrics_status"] = metrics_status
    reviewed_record["study_metrics"] = study_metrics
    reviewed_record["review"] = {
        "reviewed_at_utc": reviewed_ts,
        "reviewer": _clean_text(reviewer),
        "notes": _clean_text(notes),
        "manual_review_completed": mark_reviewed,
        "source_record": record_path.name,
        "source_record_sha256": session.sha256_file(record_path),
        "source_events": events_path.name,
        "source_events_sha256": session.sha256_file(events_path),
        "processing_log_path": str(log_path) if log_path is not None else None,
        "processing_log_sha256": log_sha256,
        "processing_log_parse_errors": log_errors,
        "added_manual_action_count": len(added_manual),
    }

    trajectory = _build_trajectory(executions, manual_groups)
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else source_dir
    reviewed_path = _io.write_atomic_text(
        target_dir / REVIEWED_RECORD_FILENAME,
        _io.format_json(reviewed_record, trailing_newline=True),
        prefix=".human-reference-record-reviewed-",
    )
    trajectory_path = _io.write_atomic_text(
        target_dir / TRAJECTORY_FILENAME,
        _io.format_jsonl(trajectory),
        prefix=".human-trajectory-",
    )
    return ReviewResult(
        reviewed_record_path=reviewed_path,
        trajectory_path=trajectory_path,
        record=reviewed_record,
        trajectory_entries=trajectory,
    )


def format_review_summary(result: ReviewResult) -> str:
    """Format a concise human-readable summary of a completed review."""
    sess = result.record["session"]
    status = sess["metrics_status"]
    if status == metrics.METRICS_STATUS_REVIEWED:
        tools = sess["tools"] or []
        tool_text = ", ".join(tools) if tools else "none"
        metrics_line = f"metrics: reviewed  steps: {sess['steps']}  tools: {tool_text}"
    else:
        reasons = ", ".join(result.record["study_metrics"].get("pending_reasons") or [])
        metrics_line = f"metrics: pending review ({reasons})"
    return "\n".join(
        [
            f"session reviewed for {result.record['task_id']}",
            metrics_line,
            f"trajectory entries: {len(result.trajectory_entries)}",
            f"reviewed record: {result.reviewed_record_path}",
            f"trajectory: {result.trajectory_path}",
            "note: raw events.jsonl, human-reference-record.json, and task YAML were not modified",
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiment_plugin.review",
        description="Non-destructively review a recorded human-baseline session take.",
    )
    parser.add_argument("session_dir", help="Path to an immutable session-<ts>/ directory")
    parser.add_argument(
        "--manual-action",
        action="append",
        default=[],
        help="Audited manual GIS action group description (repeatable)",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        help="Optional tool id paired by position with --manual-action (repeatable)",
    )
    parser.add_argument("--processing-log", default="", help="Optional QGIS processing.log path")
    parser.add_argument("--reviewer", default="", help="Reviewer identifier")
    parser.add_argument("--notes", default="", help="Review notes")
    parser.add_argument(
        "--mark-reviewed",
        action="store_true",
        help="Confirm manual review is complete",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory for reviewed artifacts (defaults to session_dir)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for non-destructive post-session review."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if len(args.tool) > len(args.manual_action):
        print(
            "cannot review session: more --tool flags than --manual-action entries",
            file=sys.stderr,
        )
        return 2
    manual_inputs = [
        ReviewActionInput(
            action_group=group,
            tool=args.tool[idx] if idx < len(args.tool) else None,
        )
        for idx, group in enumerate(args.manual_action)
    ]
    try:
        result = review_session(
            args.session_dir,
            manual_actions=manual_inputs,
            mark_reviewed=args.mark_reviewed,
            reviewer=args.reviewer or None,
            notes=args.notes or None,
            processing_log=args.processing_log or None,
            output_dir=args.output_dir or None,
        )
    except (ReviewError, ValueError) as exc:
        print(f"cannot review session: {exc}", file=sys.stderr)
        return 1
    print(format_review_summary(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
