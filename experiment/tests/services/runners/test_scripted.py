"""Unit tests for ``experiment.services.runners.scripted``."""

from __future__ import annotations

import json
from pathlib import Path

from experiment.adapters import harness_io, task_repository
from experiment.services.runners import scripted_arm_a, scripted_arm_b
from experiment.services.runners.ports import CellRequest


def test_scripted_arm_a_and_arm_b_produce_valid_deliverables(tmp_path: Path) -> None:
    task_path = harness_io.TASK_ROOT / "analysis-de9im-001.yaml"
    task = task_repository.load_task(task_path)

    for arm, runner_fn in (("A", scripted_arm_a), ("B", scripted_arm_b)):
        cell = tmp_path / f"cell-{arm}"
        cell.mkdir()
        req = CellRequest(
            task_path=task_path,
            task=task,
            arm=arm,
            driver="scripted",
            cell=cell,
            model="scripted",
            host="http://127.0.0.1:11434",
            run_id="scripted-test",
        )
        runner_fn(req)
        result = json.loads((cell / "result.json").read_text(encoding="utf-8"))
        assert result["relation"] == "touches"
        assert (cell / "transcript.jsonl").is_file()
