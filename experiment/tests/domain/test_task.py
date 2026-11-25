"""Unit tests for ``experiment.domain.task``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiment.domain.task import Task

TASKS_DIR = Path(__file__).resolve().parents[2] / "tasks"


def test_model_and_schema_agree_on_every_required_key() -> None:
    schema = json.loads((TASKS_DIR / "schema-v1.json").read_text(encoding="utf-8"))
    required_in_schema = set(schema["required"])
    required_in_model = {name for name, field in Task.model_fields.items() if field.is_required()}
    assert required_in_model == required_in_schema


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
