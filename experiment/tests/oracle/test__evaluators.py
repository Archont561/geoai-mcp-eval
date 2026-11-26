"""Unit tests for ``experiment.oracle._evaluators``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.oracle import _evaluate_assertion

UTF8 = "utf-8"
FEATURES_KEY = "features"
TYPE_KEY = "type"
AXIS_TASK = "prep-axis-order-001"


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(count=0, suffix="outside")
@given(
    count=st.integers(min_value=0, max_value=20),
    suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=15),
)
def test_geojson_feature_count_and_oracle_path_traversal(
    tmp_path: Path, count: int, suffix: str
) -> None:
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "result.geojson",
        "expected": count,
    }
    (tmp_path / "result.geojson").write_text(
        json.dumps({TYPE_KEY: "FeatureCollection", FEATURES_KEY: [{} for _ in range(count)]}),
        encoding=UTF8,
    )
    assert _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["expected"] = count + 1
    assert not _evaluate_assertion(assertion, tmp_path, tmp_path).passed
    assertion["output"] = f"../{suffix}.json"
    with pytest.raises(ValueError, match="escapes"):
        _evaluate_assertion(assertion, tmp_path, tmp_path)


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(invalid={TYPE_KEY: "Feature", FEATURES_KEY: []})
@example(invalid=[])
@given(
    invalid=st.one_of(
        st.lists(st.integers(), max_size=5),
        st.integers().map(lambda n: {TYPE_KEY: "Feature", FEATURES_KEY: [n]}),
        st.text(max_size=20).map(lambda text: {TYPE_KEY: "FeatureCollection", FEATURES_KEY: text}),
    )
)
def test_oracle_rejects_invalid_geojson_output(tmp_path: Path, invalid: object) -> None:
    output_path = tmp_path / "bad.geojson"
    output_path.write_text(json.dumps(invalid), encoding=UTF8)
    assertion = {
        "id": "count",
        TYPE_KEY: "geojson_feature_count",
        "output": "bad.geojson",
        "expected": 0,
    }
    with pytest.raises(ValueError):
        _evaluate_assertion(assertion, tmp_path, tmp_path)
