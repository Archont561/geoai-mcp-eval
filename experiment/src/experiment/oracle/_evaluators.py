"""Type-specific oracle assertion evaluators for pilot tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from shapely.geometry import shape

from ._base import AssertionResult, OracleVerdict, geojson_features, read_json, safe_path
from ._jenks import jenks_assignments


@dataclass(frozen=True)
class _EvalContext:
    assertion: dict[str, object]
    task_root: Path
    output_path: Path

    @property
    def assertion_id(self) -> str:
        return str(self.assertion.get("id", "<unnamed>"))


def _evaluate_feature_count(assertion: dict[str, object], output_path: Path) -> AssertionResult:
    assertion_id = str(assertion.get("id", "<unnamed>"))
    features = geojson_features(output_path)
    expected = assertion.get("expected")
    return AssertionResult(
        assertion_id,
        len(features) == expected,
        f"feature count {len(features)}; expected {expected}",
    )


def _representative_point_reference(
    assertion: dict[str, object], task_root: Path
) -> tuple[dict[str, object], object, str]:
    fixture_path = safe_path(task_root, str(assertion["fixture"]))
    id_field = str(assertion["id_field"])
    feature_id = str(assertion["feature_id"])
    matches = [
        feature
        for feature in geojson_features(fixture_path)
        if feature.get("properties", {}).get(id_field) == feature_id
    ]
    if len(matches) != 1:
        raise ValueError(f"fixture must contain exactly one feature with {id_field}={feature_id}")
    source_feature = matches[0]
    expected_point = shape(source_feature["geometry"]).representative_point()
    return source_feature, expected_point, id_field


def _preserved_fields_issue(
    assertion_id: str,
    output_properties: dict[str, object],
    source_properties: dict[str, object],
    preserve_fields: list[str],
) -> AssertionResult | None:
    for field in preserve_fields:
        expected = source_properties.get(field)
        if output_properties.get(field) != expected:
            return AssertionResult(
                assertion_id,
                False,
                f"output feature must preserve {field}={expected!r}",
            )
    return None


def _point_geometry_issue(
    assertion_id: str, output_feature: dict[str, object]
) -> AssertionResult | None:
    geometry = output_feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return AssertionResult(assertion_id, False, "output geometry must be a GeoJSON Point")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return AssertionResult(
            assertion_id, False, "output point must have [longitude, latitude] coordinates"
        )
    return None


def _point_feature_issue(
    assertion_id: str,
    output_feature: dict[str, object],
    source_feature: dict[str, object],
    preserve_fields: list[str],
) -> AssertionResult | None:
    output_properties = output_feature.get("properties")
    if not isinstance(output_properties, dict):
        return AssertionResult(assertion_id, False, "output feature must have a properties object")
    source_properties = source_feature.get("properties", {})
    issue = _preserved_fields_issue(
        assertion_id, output_properties, source_properties, preserve_fields
    )
    return issue if issue is not None else _point_geometry_issue(assertion_id, output_feature)


def _point_output_issue(
    assertion_id: str,
    output_features: list[dict[str, object]],
    source_feature: dict[str, object],
    preserve_fields: list[str],
) -> AssertionResult | None:
    if len(output_features) != 1:
        return AssertionResult(
            assertion_id,
            False,
            f"expected one output point; found {len(output_features)} features",
        )
    return _point_feature_issue(assertion_id, output_features[0], source_feature, preserve_fields)


def _evaluate_representative_point(ctx: _EvalContext) -> AssertionResult:
    assertion_id = ctx.assertion_id
    source_feature, expected_point, id_field = _representative_point_reference(
        ctx.assertion, ctx.task_root
    )
    output_features = geojson_features(ctx.output_path)
    preserve_fields = ctx.assertion.get("preserve_fields", [id_field])
    issue = _point_output_issue(assertion_id, output_features, source_feature, preserve_fields)
    if issue is not None:
        return issue
    coordinates = output_features[0]["geometry"]["coordinates"]
    tolerance = float(ctx.assertion.get("tolerance_degrees", 0.0))
    passed = (
        abs(float(coordinates[0]) - expected_point.x) <= tolerance
        and abs(float(coordinates[1]) - expected_point.y) <= tolerance
    )
    return AssertionResult(
        assertion_id,
        passed,
        f"point is [{coordinates[0]}, {coordinates[1]}]; "
        f"expected lon/lat [{expected_point.x}, {expected_point.y}] "
        f"within {tolerance}°",
    )


def _load_relation_geometries(
    assertion: dict[str, object], task_root: Path
) -> tuple[object, object]:
    fixture_path = safe_path(task_root, str(assertion["fixture"]))
    id_field = str(assertion["id_field"])
    by_id = {
        feature.get("properties", {}).get(id_field): feature
        for feature in geojson_features(fixture_path)
    }
    left_id = str(assertion["left_id"])
    right_id = str(assertion["right_id"])
    if left_id not in by_id or right_id not in by_id:
        raise ValueError(f"fixture lacks required feature IDs {left_id!r}, {right_id!r}")
    return shape(by_id[left_id]["geometry"]), shape(by_id[right_id]["geometry"])


def _de9im_relation(left: object, right: object, relation_name: str) -> tuple[str, str]:
    matrix = left.relate(right)
    relation_value = bool(getattr(left, relation_name)(right))
    actual_relation = relation_name if relation_value else "not_" + relation_name
    return matrix, actual_relation


def _evaluate_de9im(ctx: _EvalContext) -> AssertionResult:
    assertion_id = ctx.assertion_id
    left, right = _load_relation_geometries(ctx.assertion, ctx.task_root)
    matrix, actual_relation = _de9im_relation(left, right, str(ctx.assertion["expected_relation"]))
    expected_matrix = str(ctx.assertion["expected_matrix"])
    if matrix != expected_matrix:
        return AssertionResult(
            assertion_id,
            False,
            f"fixture relation matrix is {matrix}; expected {expected_matrix}",
        )
    submitted = read_json(ctx.output_path)
    return _relation_result(assertion_id, submitted, matrix, actual_relation)


def _relation_result(
    assertion_id: str,
    submitted: dict[str, object],
    matrix: str,
    relation: str,
) -> AssertionResult:
    only_expected_keys = set(submitted) == {"relation", "de9im"}
    de9im_matches = submitted.get("de9im") == matrix
    relation_matches = submitted.get("relation") == relation
    passed = only_expected_keys and de9im_matches and relation_matches
    message = (
        f"submitted relation={submitted.get('relation')!r}, "
        f"de9im={submitted.get('de9im')!r}; expected relation={relation!r}, "
        f"de9im={matrix!r}"
    )
    return AssertionResult(assertion_id, passed, message)


def _evaluate_jenks(ctx: _EvalContext) -> AssertionResult:
    assertion_id = ctx.assertion_id
    fixture_path = safe_path(ctx.task_root, str(ctx.assertion["fixture"]))
    breaks, assignments = jenks_assignments(
        fixture_path,
        str(ctx.assertion["id_field"]),
        str(ctx.assertion["value_field"]),
        int(ctx.assertion["class_count"]),
    )
    submitted = read_json(ctx.output_path)
    expected_payload = {
        "method": "jenks",
        "class_count": len(breaks),
        "breaks": breaks,
        "assignments": assignments,
    }
    has_only_expected_keys = set(submitted) == set(expected_payload)
    values_match = all(submitted.get(key) == value for key, value in expected_payload.items())
    passed = has_only_expected_keys and values_match
    return AssertionResult(
        assertion_id,
        passed,
        f"Jenks result has {len(breaks)} classes and {len(assignments)} assignments; "
        f"breaks and assignments {'match' if passed else 'do not match'} "
        "the fixture oracle",
    )


def _evaluate_assertion(
    assertion: dict[str, object], task_root: Path, artifact_root: Path
) -> AssertionResult:
    """Dispatch one assertion to its type-specific oracle implementation."""
    output_path = safe_path(artifact_root, str(assertion.get("output", "")))
    ctx = _EvalContext(assertion=assertion, task_root=task_root, output_path=output_path)
    handlers = {
        "geojson_feature_count": lambda: _evaluate_feature_count(assertion, output_path),
        "representative_point_matches": lambda: _evaluate_representative_point(ctx),
        "de9im_relation": lambda: _evaluate_de9im(ctx),
        "jenks_classification": lambda: _evaluate_jenks(ctx),
    }
    handler = handlers.get(str(assertion.get("type")))
    if handler is None:
        raise ValueError(f"unimplemented oracle type: {assertion.get('type')!r}")
    return handler()


def evaluate_task(task_path: Path, artifact_root: Path) -> OracleVerdict:
    """Evaluate every assertion for a task against one fixed artifact directory."""
    task_path = task_path.resolve()
    task_root = task_path.parent
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        raise ValueError("task YAML must contain a mapping")
    checks: list[AssertionResult] = []
    for assertion in task.get("oracle", {}).get("assertions", []):
        assertion_id = str(assertion.get("id", "<unnamed>"))
        try:
            checks.append(_evaluate_assertion(assertion, task_root, artifact_root))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            checks.append(
                AssertionResult(assertion_id, False, f"oracle could not evaluate assertion: {exc}")
            )
    return OracleVerdict(bool(checks) and all(check.passed for check in checks), tuple(checks))
