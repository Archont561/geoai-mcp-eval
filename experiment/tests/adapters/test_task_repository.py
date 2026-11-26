"""Properties of task discovery, loading, and diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters.task_repository import (
    TaskLoadError,
    load_task,
    read_task_document,
)
from experiment.domain.task import Task

names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20)
fixture_settings = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])


@fixture_settings
@given(extra=names.filter(lambda key: key not in Task.model_fields))
def test_unknown_fields_are_rejected(
    tmp_path: Path, sample_task_document: dict[str, Any], extra: str
) -> None:
    path = tmp_path / "extra.yaml"
    path.write_text(yaml.safe_dump({**sample_task_document, extra: True}), encoding="utf-8")
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert extra in excinfo.value.reason
    assert excinfo.value.path == path


@fixture_settings
@given(name=names)
def test_missing_task_reports_read_failure(tmp_path: Path, name: str) -> None:
    path = tmp_path / f"{name}.absent"
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.path == path
    assert excinfo.value.reason.startswith("cannot read: ")


@fixture_settings
@given(label=names)
def test_malformed_task_reports_parse_failure(tmp_path: Path, label: str) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text(f"{label}: [unclosed\n", encoding="utf-8")
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.path == path
    assert excinfo.value.reason.startswith("cannot parse YAML: ")


@fixture_settings
@given(items=st.lists(names, max_size=5))
def test_non_mapping_documents_are_rejected(tmp_path: Path, items: list[str]) -> None:
    path = tmp_path / "list.yaml"
    path.write_text(yaml.safe_dump(items), encoding="utf-8")
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert excinfo.value.reason == "task document must be a YAML mapping"


@fixture_settings
@given(key=names)
def test_unvalidated_mapping_can_be_read(tmp_path: Path, key: str) -> None:
    path = tmp_path / "incomplete.yaml"
    document = {key: "value"}
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert read_task_document(path) == document


@fixture_settings
@given(key=st.sampled_from(["id", "fixtures", "title", "prompt"]))
def test_missing_required_fields_are_reported(
    tmp_path: Path, sample_task_document: dict[str, Any], key: str
) -> None:
    document = dict(sample_task_document)
    del document[key]
    path = tmp_path / "incomplete.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(TaskLoadError) as excinfo:
        load_task(path)
    assert key in excinfo.value.reason
