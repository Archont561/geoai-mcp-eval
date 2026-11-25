"""Unit tests for ``experiment.domain.task``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.task import (
    BaselineStatus,
    Contamination,
    Expressibility,
    Task,
    TaskFamily,
)

TASKS_DIR = Path(__file__).resolve().parents[2] / "tasks"


def test_model_and_schema_agree_on_every_required_key() -> None:
    schema = json.loads((TASKS_DIR / "schema-v1.json").read_text(encoding="utf-8"))
    model_schema = Task.model_json_schema()
    required_in_schema = set(schema["required"])
    required_in_model = {name for name, field in Task.model_fields.items() if field.is_required()}
    assert required_in_model == required_in_schema
    assert set(model_schema["required"]) == required_in_schema
    assert set(model_schema["properties"]) == set(schema["properties"])
    assert set(schema["properties"]["family"]["enum"]) == {f.value for f in TaskFamily}


def test_model_forbids_unknown_keys_like_the_schema_does() -> None:
    with pytest.raises(ValidationError):
        Task.model_validate(
            {
                "id": "demo-001",
                "title": "Demo",
                "family": "A",
                "prompt": "Compute area",
                "fixtures": {"input": "fixtures/a.geojson"},
                "deliverables": ["result.json"],
                "oracle": {"type": "json_equals", "output": "result.json"},
                "unexpected_key": True,
            }
        )


@given(family=st.sampled_from(list(TaskFamily)))
def test_task_family_display_name_and_required_pilot_families(family: TaskFamily) -> None:
    assert family.display_name()
    assert family in TaskFamily.required_pilot_families()


@given(
    enum_cls=st.sampled_from([TaskFamily, Expressibility, Contamination, BaselineStatus]),
)
def test_task_str_enums_roundtrip_by_value(enum_cls: type[TaskFamily]) -> None:
    for member in enum_cls:
        assert enum_cls(member.value) is member
        assert str(member) == member.value
