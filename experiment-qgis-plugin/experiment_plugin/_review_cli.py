"""CLI argument parsing and summary formatting for post-session review."""

from __future__ import annotations

import argparse
from typing import Any

from experiment_plugin import metrics


def format_review_summary(result: Any) -> str:
    """Format a concise human-readable summary of a completed review."""
    sess = result.record["session"]
    status = sess["metrics_status"]
    if status == metrics.METRICS_STATUS_REVIEWED:
        tools = sess["tools"] or []
        tool_text = ", ".join(tools) if tools else "none"
        metrics_line = f"metrics: reviewed  steps: {sess['steps']}  tools: {tool_text}"
    else:
        reasons = ", ".join(result.record["study_metrics"]["pending_reasons"])
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


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--mark-reviewed", action="store_true", help="Confirm review is complete")
    parser.add_argument("--output-dir", default="", help="Directory for reviewed artifacts")
    return parser


def _pair_actions(args: Any, action_cls: Any) -> list[Any]:
    return [
        action_cls(action_group=group, tool=args.tool[i] if i < len(args.tool) else None)
        for i, group in enumerate(args.manual_action)
    ]


def run_cli(argv: Any, *, review_fn: Any, action_cls: Any, error_cls: type[Exception]) -> int:
    """Execute the post-session review CLI."""
    import sys

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if len(args.tool) > len(args.manual_action):
        print(
            "cannot review session: more --tool flags than --manual-action entries",
            file=sys.stderr,
        )
        return 2
    try:
        result = review_fn(
            args.session_dir,
            manual_actions=_pair_actions(args, action_cls),
            mark_reviewed=args.mark_reviewed,
            reviewer=args.reviewer or None,
            notes=args.notes or None,
            processing_log=args.processing_log or None,
            output_dir=args.output_dir or None,
        )
    except (error_cls, ValueError) as exc:
        print(f"cannot review session: {exc}", file=sys.stderr)
        return 1
    print(format_review_summary(result))
    return 0
