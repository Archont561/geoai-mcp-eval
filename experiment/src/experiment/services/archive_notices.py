"""Compact GitHub Actions check-run notices for packed ``RunArchive`` bundles."""

from __future__ import annotations

import json
from typing import Any

from experiment.adapters.github_workflow import GitHubWorkflowAdapter
from experiment.domain.run import ExperimentRun, TrialMeasurement, TrialRecord

_CODEGEN_CHUNK_SIZE = 3


def _parse_transcript_bytes(raw: bytes | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    entries: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _codegen_trial_evidence(
    record: TrialRecord, measurement: TrialMeasurement, payloads: dict[str, bytes]
) -> dict[str, Any]:
    entries = _parse_transcript_bytes(payloads.get("transcript.jsonl"))
    assistant = next((e for e in entries if e.get("role") == "assistant"), {})
    tool_res = next((e for e in entries if e.get("role") == "tool_result"), {})
    no_fence = any(
        e.get("role") == "harness" and e.get("content") == "no python block found" for e in entries
    )
    reply_text = str(assistant.get("content") or "")
    assertions = [
        {"id": a.assertion_id, "ok": a.passed, "d": a.detail[:80]} for a in measurement.assertions
    ]
    return {
        "id": record.trial_id,
        "task": record.key.task_id,
        "rep": record.key.repetition,
        "ok": measurement.outcomes.task_success,
        "mps": round(measurement.outcomes.predicate_score, 4),
        "wall_s": round(measurement.economics.wall_seconds, 2),
        "tok": measurement.economics.tokens.total_tokens,
        "fence": bool(assistant) and not no_fence,
        "rc": tool_res.get("returncode"),
        "reply_len": len(reply_text),
        "reply_head": reply_text[:220],
        "stdout_head": str(tool_res.get("stdout") or "")[:140],
        "stderr_head": str(tool_res.get("stderr") or "")[:140],
        "assertions": assertions,
    }


def _summary_trial_row(tid: str, record: TrialRecord, m: TrialMeasurement) -> dict[str, Any]:
    return {
        "id": tid,
        "task": record.key.task_id,
        "paradigm": record.key.paradigm,
        "rep": record.key.repetition,
        "status": record.status,
        "ok": m.outcomes.task_success,
        "mps": round(m.outcomes.predicate_score, 4),
        "si": m.outcomes.silent_invalid,
        "wall_s": round(m.economics.wall_seconds, 2),
        "tok": m.economics.tokens.total_tokens,
        "a": {a.assertion_id: a.passed for a in m.assertions},
    }


def build_run_summary_notice(run: ExperimentRun) -> dict[str, Any]:
    """Build a compact JSON-serializable run overview for CI annotations."""
    model_pin = run.provenance.model
    env_pin = run.provenance.environment
    rows = [_summary_trial_row(tid, rec, run.measurements[tid]) for tid, rec in run.trials.items()]
    return {
        "run_id": run.run_id,
        "stage": run.stage,
        "model": model_pin.tag if model_pin else None,
        "digest": model_pin.digest if model_pin else None,
        "env": {
            "sha": env_pin.repo_sha,
            "py": env_pin.python,
            "ollama": env_pin.ollama,
            "qgis": env_pin.qgis,
        },
        "trials": rows,
    }


def emit_ci_notices(
    run: ExperimentRun,
    trial_payloads: dict[str, dict[str, bytes]],
    *,
    adapter: GitHubWorkflowAdapter | None = None,
) -> None:
    """Emit structured GitHub Actions ``::notice::`` annotations when in CI."""
    gha = adapter if adapter is not None else GitHubWorkflowAdapter()
    if not gha.is_actions:
        return
    summary_json = json.dumps(build_run_summary_notice(run), separators=(",", ":"))
    gha.write_notice("RunArchive Summary", summary_json)
    codegen_rows = [
        _codegen_trial_evidence(rec, run.measurements[tid], trial_payloads.get(tid, {}))
        for tid, rec in run.trials.items()
        if rec.key.paradigm == "codegen"
    ]
    for idx in range(0, len(codegen_rows), _CODEGEN_CHUNK_SIZE):
        batch = codegen_rows[idx : idx + _CODEGEN_CHUNK_SIZE]
        part = (idx // _CODEGEN_CHUNK_SIZE) + 1
        body = json.dumps({"run_id": run.run_id, "codegen": batch}, separators=(",", ":"))
        gha.write_notice(f"Codegen Evidence {part}", body)
