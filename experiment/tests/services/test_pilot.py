"""Unit tests for ``experiment.services.pilot``."""

from __future__ import annotations

import json
from pathlib import Path

from experiment.services import pilot


def test_pilot_service_delegates_suite_validation_and_determinism(tmp_path: Path) -> None:
    root = pilot.default_task_root()
    assert root.is_dir()
    task_file = pilot.find_task_file(root, "analysis-de9im-001")
    assert task_file.is_file()
    report = pilot.validate_suite(root)
    assert report.passed is True

    (tmp_path / "result.json").write_text(
        json.dumps({"relation": "touches", "de9im": "FF2F11212"}),
        encoding="utf-8",
    )
    gate = pilot.run_determinism_gate(task_file, tmp_path)
    assert gate.passed is True
    assert gate.consistent is True
