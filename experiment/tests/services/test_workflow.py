"""Unit tests for ``experiment.services.workflow``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from experiment.adapters import subprocess_runner
from experiment.services import workflow

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_workflow_harvest_runs_determinism_gate_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)

    def fail_subprocess(cmd: list[str], **_kw: Any) -> Any:
        raise AssertionError(f"harvest must not spawn CLI subprocess: {cmd}")

    monkeypatch.setattr(subprocess_runner, "run_command", fail_subprocess)
    harvest = tmp_path / "harvest"
    cell = harvest / "experiment-A-analysis-de9im-001-rep1"
    cell.mkdir(parents=True)
    (cell / "manifest.json").write_text(
        json.dumps({"arm": "A", "task": "analysis-de9im-001", "rep": 1, "status": "ok"}),
        encoding="utf-8",
    )
    summary = workflow.run_harvest(
        workflow.HarvestConfig(
            harvest_dir=harvest,
            arms=("A",),
            repetitions=1,
            fail_on_missing=False,
            skip_oracle=False,
            run_id="rid-det",
        )
    )
    assert summary["oracle"] == {"analysis-de9im-001/A/rep-1": "fail"}
    gate_file = harvest / "oracle" / "analysis-de9im-001-A-rep1.json"
    assert gate_file.is_file()
    payload = json.loads(gate_file.read_text(encoding="utf-8"))
    assert payload["required_runs"] == 3
    assert payload["passed"] is False


def test_harvest_config_pydantic_validation(tmp_path: Path) -> None:
    cfg = workflow.HarvestConfig(harvest_dir=tmp_path, repetitions=2)
    assert cfg.repetitions == 2
    with pytest.raises(ValidationError):
        workflow.HarvestConfig(harvest_dir=tmp_path, repetitions=0)
    with pytest.raises(ValidationError):
        workflow.HarvestConfig(harvest_dir=tmp_path, extra_key=True)  # type: ignore[call-arg]


def test_ci_workflow_has_opt_in_llm_cache_with_prefix_restore_keys() -> None:
    wf = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/experiment.yml").read_text(encoding="utf-8")
    )
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["use-llm-cache"]["type"] == "boolean"
    assert inputs["use-llm-cache"]["default"] is False
    steps = wf["jobs"]["run"]["steps"]
    cache_steps = [s for s in steps if s.get("with", {}).get("path") == ".cache/llm"]
    assert len(cache_steps) == 1
    step = cache_steps[0]
    assert "actions/cache@" in step["uses"]
    assert "llm-cache-" in step["with"]["restore-keys"]
