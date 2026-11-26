"""Behavioral tests for the pilot task-suite validator."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters.task_suite import (
    _resolve_inside,
    _schema_validation_issues,
)

TYPE_KEY = "type"
SAFE_SEGMENTS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=8),
    min_size=1,
    max_size=3,
)


@given(segments=SAFE_SEGMENTS)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resolve_inside_accepts_arbitrary_nested_relative_paths(
    tmp_path: Path, segments: list[str]
) -> None:
    rel = "/".join(segments)
    resolved = _resolve_inside(tmp_path, rel)
    assert resolved.is_relative_to(tmp_path.resolve())


@given(segments=SAFE_SEGMENTS)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_resolve_inside_rejects_escaping_paths(tmp_path: Path, segments: list[str]) -> None:
    for unsafe in ("/" + "/".join(segments), "../" + "/".join(segments)):
        with pytest.raises(ValueError):
            _resolve_inside(tmp_path, unsafe)


@given(negative=st.integers(max_value=-1), tag=st.text(alphabet="abc", min_size=1, max_size=8))
def test_standard_jsonschema_keywords_are_supported(negative: int, tag: str) -> None:
    issues = _schema_validation_issues(
        {"name": "", "count": negative, "tags": [tag, tag], "extra": 1},
        {
            TYPE_KEY: "object",
            "required": ["missing"],
            "additionalProperties": False,
            "properties": {
                "name": {TYPE_KEY: "string", "minLength": 1, "pattern": "^[A-Z]+$"},
                "count": {TYPE_KEY: "integer", "minimum": 0, "maximum": 2},
                "tags": {TYPE_KEY: "array", "uniqueItems": True, "items": {TYPE_KEY: "string"}},
            },
            "allOf": [{"minProperties": 5}],
        },
    )
    messages = " ".join(issue.message for issue in issues)
    assert "missing' is a required property" in messages
    assert "Additional properties are not allowed" in messages
    assert "should be non-empty" in messages
    assert "does not match" in messages
    assert "less than the minimum" in messages
    assert "has non-unique elements" in messages
    assert "does not have enough properties" in messages
    issues = _schema_validation_issues(1, {TYPE_KEY: "string"})
    assert "is not of type 'string'" in issues[0].message
