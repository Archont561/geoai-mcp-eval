"""Tests for TrialMeasurement DTO wiring: oracle, economics, determinism, human ref (GEO-017)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.domain.run import (
    AssertionResult,
    DeterminismAudit,
    TokenUsage,
    TrialKey,
    TrialMeasurement,
    infer_assertion_tier,
)
from experiment.domain.run.metrics import extract_transcript_metrics
from experiment.oracle import run_determinism_gate
from experiment.services.measurement import (
    TrialMeasurementOptions,
    determinism_report_to_audit,
    measure_human_reference,
    measure_trial,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = REPO_ROOT / "experiment" / "tasks"


def test_infer_assertion_tier_maps_legacy_letters_and_types() -> None:
    assert infer_assertion_tier("geojson_feature_count") == "trivial"
    assert infer_assertion_tier("representative_point_matches") == "spatial"
    assert infer_assertion_tier("de9im_relation") == "spatial"
    assert infer_assertion_tier("jenks_classification") == "value"
    assert infer_assertion_tier("custom_type", explicit_tier="A") == "trivial"
    assert infer_assertion_tier("custom_type", explicit_tier="B") == "spatial"
    assert infer_assertion_tier("custom_type", explicit_tier="C") == "value"
    assert infer_assertion_tier("custom_type", explicit_tier="spatial") == "spatial"
    assert infer_assertion_tier("unknown_type") is None


def test_extract_transcript_metrics_counts_calls_repairs_and_violations() -> None:
    entries = [
        {"role": "meta", "task": "analysis-de9im-001"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "filter_features", "arguments": "{}"}},
                {"id": "2", "function": {"name": "relate_de9im", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_name": "filter_features", "error_code": "INVALID_SCHEMA"},
        {"role": "assistant", "content": '{"relation": "touches", "de9im": "FF2F11212"}'},
        {
            "role": "harness",
            "event": "usage_summary",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 40,
                "total_tokens": 160,
                "llm_calls": 2,
                "calls_with_usage": 2,
                "calls_missing_usage": 0,
                "max_cell_tokens": None,
                "cap_exceeded": False,
                "warnings": [],
            },
        },
    ]
    metrics = extract_transcript_metrics(entries, wall_seconds=3.25)
    assert metrics.wall_seconds == 3.25
    assert metrics.llm_calls == 2
    assert metrics.tool_calls == 2
    assert metrics.schema_violations == 1
    assert metrics.repair_turns == 1
    assert metrics.tokens.total_tokens == 160

    empty = extract_transcript_metrics([])
    assert empty.llm_calls == 0
    assert empty.tool_calls == 0
    assert empty.repair_turns == 0
    assert empty.schema_violations == 0
    assert empty.tokens.total_tokens is None


def test_measure_trial_detects_silent_invalid_vs_missing_and_valid(tmp_path: Path) -> None:
    prep_task = TASKS_ROOT / "prep-axis-order-001.yaml"
    key = TrialKey(
        task_id="prep-axis-order-001",
        paradigm="codegen",
        enforcement_level="none",
        repetition=1,
    )

    # 1) Silent-invalid: valid 1-feature GeoJSON, but lat/lon axes are swapped!
    silent_dir = tmp_path / "silent"
    silent_dir.mkdir()
    swapped_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
                "geometry": {"type": "Point", "coordinates": [52.0, 19.0]},
            }
        ],
    }
    (silent_dir / "result.geojson").write_text(json.dumps(swapped_fc), encoding="utf-8")
    (silent_dir / "transcript.jsonl").write_text(
        json.dumps({"role": "assistant", "content": "```python\nprint(1)\n```"})
        + "\n"
        + json.dumps({"role": "tool_result", "returncode": 0, "stdout": "{}"})
        + "\n",
        encoding="utf-8",
    )
    dto_silent = measure_trial(
        prep_task,
        silent_dir,
        key=key,
        options=TrialMeasurementOptions(wall_seconds=2.5),
    )
    assert isinstance(dto_silent, TrialMeasurement)
    assert dto_silent.outcomes.task_success is False
    assert dto_silent.outcomes.predicate_score == pytest.approx(0.5)
    assert dto_silent.outcomes.silent_invalid is True
    by_id = {a.assertion_id: a for a in dto_silent.assertions}
    assert by_id["single-output-feature"].tier == "trivial"
    assert by_id["single-output-feature"].predicate == "feature_count"
    assert by_id["single-output-feature"].passed is True
    assert by_id["representative-point-axis-order"].tier == "spatial"
    assert by_id["representative-point-axis-order"].predicate == "point_axis_order"
    assert by_id["representative-point-axis-order"].passed is False

    # 2) Missing deliverable: trivial assertion fails -> NOT silent_invalid
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    dto_empty = measure_trial(prep_task, empty_dir, key=key)
    assert dto_empty.outcomes.task_success is False
    assert dto_empty.outcomes.predicate_score == 0.0
    assert dto_empty.outcomes.silent_invalid is False

    # 3) Single-assertion spatial task with readable-but-wrong JSON -> silent_invalid=True
    de9im_task = TASKS_ROOT / "analysis-de9im-001.yaml"
    de9im_key = TrialKey(
        task_id="analysis-de9im-001",
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=1,
    )
    wrong_de9im = tmp_path / "wrong-de9im"
    wrong_de9im.mkdir()
    (wrong_de9im / "result.json").write_text(
        json.dumps({"relation": "disjoint", "de9im": "FF2FF1212"}),
        encoding="utf-8",
    )
    dto_de9im_bad = measure_trial(de9im_task, wrong_de9im, key=de9im_key)
    assert dto_de9im_bad.outcomes.task_success is False
    assert dto_de9im_bad.outcomes.silent_invalid is True

    # 4) Passing de9im + 3-pass determinism audit
    good_de9im = tmp_path / "good-de9im"
    good_de9im.mkdir()
    (good_de9im / "result.json").write_text(
        json.dumps({"relation": "touches", "de9im": "FF2F11212"}),
        encoding="utf-8",
    )
    det_report = run_determinism_gate(de9im_task, good_de9im)
    audit = determinism_report_to_audit(det_report)
    assert audit == DeterminismAudit(
        passes_required=3, passes_executed=3, consistent=True, passed=True, issues=[]
    )
    dto_good = measure_trial(
        de9im_task,
        good_de9im,
        key=de9im_key,
        options=TrialMeasurementOptions(
            wall_seconds=1.2,
            token_usage=TokenUsage(input_tokens=50, output_tokens=20, total_tokens=70),
            determinism=det_report,
        ),
    )
    assert dto_good.outcomes.task_success is True
    assert dto_good.outcomes.predicate_score == 1.0
    assert dto_good.outcomes.silent_invalid is False
    assert dto_good.determinism == audit
    assert dto_good.economics.tokens.total_tokens == 70


def test_measure_human_reference_converts_plugin_record_into_trial_measurement(
    tmp_path: Path,
) -> None:
    de9im_task = TASKS_ROOT / "analysis-de9im-001.yaml"
    artifacts_dir = tmp_path / "human-out"
    artifacts_dir.mkdir()
    (artifacts_dir / "result.json").write_text(
        json.dumps({"relation": "touches", "de9im": "FF2F11212"}),
        encoding="utf-8",
    )
    human_record = {
        "record_version": 2,
        "status": "complete",
        "task_id": "analysis-de9im-001",
        "participant_code": "H-01",
        "session": {
            "elapsed_minutes": 4.5,
            "steps": 5,
            "tools": ["native:extractbyattribute", "qgis:topologicalrelations"],
        },
        "study_metrics": {
            "status": "complete",
            "processing_step_count": 2,
            "manual_step_count": 3,
        },
        "oracle_passed": True,
    }
    dto = measure_human_reference(
        human_record,
        task_path=de9im_task,
        artifacts_dir=artifacts_dir,
        repetition=1,
    )
    assert dto.key.paradigm == "human_gui"
    assert dto.key.enforcement_level == "none"
    assert dto.key.task_id == "analysis-de9im-001"
    assert dto.outcomes.task_success is True
    assert dto.outcomes.predicate_score == 1.0
    assert dto.economics.wall_seconds == pytest.approx(270.0)
    assert dto.economics.human_steps == 5
    assert dto.economics.tool_calls == 2
    assert dto.economics.tokens.total_tokens is None

    # Fallback without artifacts_dir uses recorded oracle_passed flag cleanly
    record_only = measure_human_reference(human_record, repetition=2)
    assert record_only.key.repetition == 2
    assert record_only.outcomes.task_success is True
    assert record_only.assertions == [
        AssertionResult(assertion_id="recorded-oracle", passed=True, detail="from record")
    ]
