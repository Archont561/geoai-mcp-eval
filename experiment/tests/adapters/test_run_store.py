"""Unit tests for ``experiment.adapters.run_store``."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters import run_store


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(first=st.integers(-10000, 10000), second=st.integers(-10000, 10000))
def test_run_store_roundtrips_json_jsonl_pins_and_discovery(
    tmp_path: Path, first: int, second: int
) -> None:
    with TemporaryDirectory(dir=tmp_path) as directory:
        _exercise_roundtrip(Path(directory), first, second)


def _exercise_roundtrip(tmp_path: Path, first: int, second: int) -> None:
    target = run_store.write_json(
        tmp_path / "sub" / "data.json", {"b": first, "a": second}, trailing_newline=True
    )
    assert target.read_text(encoding="utf-8").endswith("\n")
    assert run_store.read_json(target) == {"a": second, "b": first}
    assert run_store.read_json_mapping(target) == {"a": second, "b": first}

    bad = run_store.write_text(tmp_path / "bad.json", "{not-json")
    assert run_store.read_json_mapping(bad) is None
    non_dict = run_store.write_json(tmp_path / "list.json", [1, 2])
    assert run_store.read_json_mapping(non_dict) is None

    jsonl = tmp_path / "events.jsonl"
    run_store.append_jsonl(jsonl, {"seq": first, "kind": "a"})
    run_store.append_jsonl(jsonl, {"seq": second, "kind": "b"})
    assert len(run_store.read_text(jsonl).splitlines()) == 2

    run_store.write_jsonl(tmp_path / "manifest.jsonl", [{"id": 1}, {"id": 2}])
    assert len(run_store.read_text(tmp_path / "manifest.jsonl").splitlines()) == 2

    pins_path = run_store.write_env_pins(tmp_path / "pins" / "env-pins.txt", {"python": "3.13"})
    assert pins_path.is_file()
    assert run_store.read_env_pins(tmp_path) == {"python": "3.13"}
    assert run_store.read_env_pins(tmp_path / "empty") == {}

    cell_a = run_store.ensure_dir(run_store.cell_dir_path(tmp_path / "harvest", "A", "t1", 1))
    run_store.write_json(cell_a / "manifest.json", {"arm": "A", "task": "t1", "rep": 1})
    assert run_store.find_cell_dir(tmp_path / "harvest", "A", "t1", 1) == cell_a
    assert run_store.find_cell_dir(tmp_path / "harvest", "B", "t1", 1) is None
    assert len(run_store.discover_manifests(tmp_path / "harvest")) == 1
    assert len(run_store.discover_cells(tmp_path / "harvest")) == 1

    hashes = run_store.artifact_hashes(cell_a)
    assert len(hashes) == 1 and hashes[0]["path"] == "manifest.json"
    assert len(str(hashes[0]["sha256"])) == 64


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    repetition=st.integers(1, 100),
    task=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12),
)
def test_canonical_cell_layout_helpers_and_discovery(
    tmp_path: Path, repetition: int, task: str
) -> None:
    with TemporaryDirectory(dir=tmp_path) as directory:
        _exercise_layout(Path(directory), repetition, task)


def _exercise_layout(tmp_path: Path, repetition: int, task: str) -> None:
    name = run_store.cell_dir_name("A", task, repetition)
    assert run_store.parse_cell_dir_name(name) == ("A", task, repetition)
    assert run_store.cell_dir_name("A", "analysis-de9im-001", 2) == "cell-A-analysis-de9im-001-r2"
    assert run_store.parse_cell_dir_name("cell-B-prep-axis-order-001-r3") == (
        "B",
        "prep-axis-order-001",
        3,
    )
    assert run_store.parse_cell_dir_name("not-a-cell") is None
    assert run_store.parse_cell_dir_name("cell-A-task-r0") is None
    with pytest.raises(ValueError, match="repetition"):
        run_store.cell_dir_name("A", "t1", 0)

    c1 = run_store.ensure_dir(run_store.cell_dir_path(tmp_path, "A", "task-1", 1))
    c2 = run_store.ensure_dir(tmp_path / "experiment-B-task-1-rep2")
    run_store.write_json(c2 / "manifest.json", {"arm": "B", "task": "task-1", "rep": 2})

    discovered = run_store.discover_cells(tmp_path)
    assert [(c.arm, c.task_id, c.repetition, c.path) for c in discovered] == [
        ("A", "task-1", 1, c1),
        ("B", "task-1", 2, c2),
    ]
    assert run_store.find_cell_dir(tmp_path, "A", "task-1", 1) == c1
    assert run_store.find_cell_dir(tmp_path, "B", "task-1", 2) == c2

    with pytest.raises(ValidationError):
        run_store.CellDir(arm="A", task_id="t1", repetition=0, path=c1)
