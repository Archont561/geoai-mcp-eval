"""Unit tests for ``experiment.services.archive``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.services import archive as archive_service
from experiment.services import runs

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_TASKS = REPO_ROOT / "experiment" / "tasks"


def test_pack_and_inspect_archive_roundtrip(tmp_path: Path) -> None:
    out_dir = tmp_path / "run-demo"
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="A", task="analysis-de9im-001", backend="local")
    )
    runs.run_experiment(REAL_TASKS, spec, out_dir)
    zip_path = tmp_path / "experiment-run-demo.zip"
    run, written = archive_service.pack_archive(
        archive_service.PackOptions(
            source_dir=out_dir,
            output_zip=zip_path,
            run_id="demo",
            stage="pilot",
            run_harvest=False,
        )
    )
    assert written == zip_path and zip_path.is_file()
    assert run.run_id == "demo"

    overview = archive_service.inspect_archive(zip_path)
    assert overview.run_id == "demo"
    assert overview.schema_version == 1
    assert overview.trial_count == 1
    assert (
        archive_service.ArchiveOverview.model_validate_json(overview.model_dump_json()) == overview
    )


def test_pack_options_pydantic_validation(tmp_path: Path) -> None:
    opts = archive_service.PackOptions(source_dir=tmp_path, repetitions=2)
    assert opts.repetitions == 2
    with pytest.raises(ValidationError):
        archive_service.PackOptions(source_dir=tmp_path, repetitions=0)
    with pytest.raises(ValidationError):
        archive_service.PackOptions(source_dir=tmp_path, bogus=1)  # type: ignore[call-arg]
    assert json.loads(opts.model_dump_json())["repetitions"] == 2
