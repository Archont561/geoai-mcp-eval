"""The task adapter: one parser, four failure modes, one unambiguous result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from cli_harness import TASK_ROOT, UTF8

from experiment.adapters.task_repository import (
    TaskLoadError,
    TaskNotFoundError,
    discover_task_files,
    find_task,
    find_task_file,
    load_suite,
    load_task,
    read_task_document,
)
from experiment.domain.task import Task

SHIPPED_SUITE = TASK_ROOT
SHIPPED_IDS = {
    "analysis-de9im-001",
    "cartography-jenks-001",
    "prep-axis-order-001",
}


def test_every_shipped_task_loads_as_a_model() -> None:
    tasks = load_suite(SHIPPED_SUITE)
    assert {task.id for task in tasks} == SHIPPED_IDS
    assert all(isinstance(task, Task) for task in tasks)


def test_discovery_excludes_the_schema_beside_the_tasks() -> None:
    discovered = {path.name for path in discover_task_files(SHIPPED_SUITE)}
    assert discovered == {f"{task_id}.yaml" for task_id in SHIPPED_IDS}
    assert "schema-v1.json" not in discovered


def test_model_and_schema_agree_on_every_required_key() -> None:
    schema = json.loads((SHIPPED_SUITE / "schema-v1.json").read_text(encoding=UTF8))
    schema_required = {
        "<root>": set(schema["required"]),
        **{
            name: set(spec["required"])
            for name, spec in schema["properties"].items()
            if isinstance(spec, dict) and "required" in spec
        },
    }
    model_required = {
        "<root>": set(Task.model_fields),
        **{
            name: set(field.annotation.model_fields)
            for name, field in Task.model_fields.items()
            if hasattr(field.annotation, "model_fields")
        },
    }
    assert model_required == schema_required


def test_model_forbids_unknown_keys_like_the_schema_does(
    tmp_path: Path, sample_task_document: dict[str, Any]
) -> None:
    path = tmp_path / "extra.yaml"
    path.write_text(yaml.safe_dump({**sample_task_document, "unexpected": True}), encoding=UTF8)
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert "unexpected" in excinfo.value.reason


def test_missing_file_reports_the_read_failure(tmp_path: Path) -> None:
    path = tmp_path / "absent.yaml"
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.path == path
    assert excinfo.value.reason.startswith("cannot read: ")


def test_malformed_yaml_reports_the_parse_failure(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed\n", encoding=UTF8)
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.reason.startswith("cannot parse YAML: ")


def test_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n", encoding=UTF8)
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.reason == "task document must be a YAML mapping"


def test_schema_violation_reports_which_field_is_missing(
    tmp_path: Path, sample_task_document: dict[str, Any]
) -> None:
    del sample_task_document["fixtures"]
    path = tmp_path / "incomplete.yaml"
    path.write_text(yaml.safe_dump(sample_task_document), encoding=UTF8)
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert "fixtures" in excinfo.value.reason


def test_read_document_returns_the_mapping_without_validating(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.yaml"
    path.write_text(yaml.safe_dump({"id": "only-an-id"}), encoding=UTF8)
    assert read_task_document(path) == {"id": "only-an-id"}


def test_unknown_id_raises_not_found(tmp_path: Path, sample_task_document: dict[str, Any]) -> None:
    (tmp_path / "task.yaml").write_text(yaml.safe_dump(sample_task_document), encoding=UTF8)
    with pytest.raises(TaskNotFoundError) as excinfo:
        find_task_file(tmp_path, "no-such-task")
    assert excinfo.value.task_id == "no-such-task"
    assert excinfo.value.suite == tmp_path
    assert "unknown task ID: no-such-task" in str(excinfo.value)


def test_not_found_is_a_lookup_error() -> None:
    assert issubclass(TaskNotFoundError, LookupError)


def test_find_task_returns_the_validated_model(
    tmp_path: Path, sample_task_document: dict[str, Any]
) -> None:
    (tmp_path / "task.yaml").write_text(yaml.safe_dump(sample_task_document), encoding=UTF8)
    assert find_task(tmp_path, "task-001").id == "task-001"


def test_an_unparsable_sibling_does_not_hide_a_valid_task(
    tmp_path: Path, sample_task_document: dict[str, Any]
) -> None:
    (tmp_path / "aaa-broken.yaml").write_text("id: [unclosed\n", encoding=UTF8)
    (tmp_path / "zzz-valid.yaml").write_text(yaml.safe_dump(sample_task_document), encoding=UTF8)
    assert find_task_file(tmp_path, "task-001").name == "zzz-valid.yaml"


def test_load_suite_refuses_to_skip_a_broken_file(
    tmp_path: Path, sample_task_document: dict[str, Any]
) -> None:
    (tmp_path / "valid.yaml").write_text(yaml.safe_dump(sample_task_document), encoding=UTF8)
    (tmp_path / "broken.yaml").write_text("id: [unclosed\n", encoding=UTF8)
    with pytest.raises(TaskLoadError) as excinfo:
        load_suite(tmp_path)
    assert excinfo.value.path.name == "broken.yaml"
