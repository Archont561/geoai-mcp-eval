"""Deterministic pilot oracle and three-pass repeatability gate."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from shapely.geometry import shape


@dataclass(frozen=True)
class AssertionResult:
    """Result of one task oracle assertion."""

    assertion_id: str
    passed: bool
    message: str


@dataclass(frozen=True)
class OracleVerdict:
    """Stable result for a complete task oracle evaluation."""

    passed: bool
    checks: tuple[AssertionResult, ...]

    def fingerprint(self) -> tuple[bool, tuple[tuple[str, bool, str], ...]]:
        """Include assertion messages so the complete verdict must repeat identically."""
        return self.passed, tuple(
            (check.assertion_id, check.passed, check.message) for check in self.checks
        )

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "checks": [asdict(check) for check in self.checks]}


@dataclass(frozen=True)
class DeterminismReport:
    """Three-pass oracle gate report."""

    passed: bool
    required_runs: int
    consistent: bool
    run_results: tuple[dict[str, object], ...]
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "required_runs": self.required_runs,
            "consistent": self.consistent,
            "run_results": list(self.run_results),
            "issues": list(self.issues),
        }


def _safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError("oracle paths must be relative")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("oracle path escapes its allowed directory")
    return resolved


def _read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object or GeoJSON object")
    return data


def _features(path: Path) -> list[dict[str, object]]:
    data = _read_json(path)
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("expected a GeoJSON FeatureCollection")
    features = data["features"]
    if not all(isinstance(feature, dict) for feature in features):
        raise ValueError("each GeoJSON feature must be an object")
    return features


def _prefix_sums(values: list[float]) -> tuple[list[float], list[float]]:
    totals = [0.0]
    squared_totals = [0.0]
    for value in values:
        totals.append(totals[-1] + value)
        squared_totals.append(squared_totals[-1] + value * value)
    return totals, squared_totals


def _within_class_error(
    totals: list[float], squared_totals: list[float], start: int, end: int
) -> float:
    size = end - start
    total = totals[end] - totals[start]
    squares = squared_totals[end] - squared_totals[start]
    return max(0.0, squares - total * total / size)


def _find_jenks_splits(values: list[float], class_count: int) -> list[list[int]]:
    count = len(values)
    totals, squared_totals = _prefix_sums(values)
    best = [[math.inf] * (count + 1) for _ in range(class_count + 1)]
    splits = [[-1] * (count + 1) for _ in range(class_count + 1)]
    best[0][0] = 0.0
    for groups in range(1, class_count + 1):
        for end in range(groups, count + 1):
            _update_best_split(groups, end, best, splits, totals, squared_totals)
    return splits


def _update_best_split(
    groups: int,
    end: int,
    best: list[list[float]],
    splits: list[list[int]],
    totals: list[float],
    squared_totals: list[float],
) -> None:
    for start in range(groups - 1, end):
        error = _within_class_error(totals, squared_totals, start, end)
        candidate = best[groups - 1][start] + error
        if candidate < best[groups][end] - 1e-9:
            best[groups][end] = candidate
            splits[groups][end] = start


def _recover_jenks_breaks(
    values: list[float], class_count: int, splits: list[list[int]]
) -> list[float]:
    boundaries: list[float] = []
    end = len(values)
    for groups in range(class_count, 0, -1):
        start = splits[groups][end]
        if start < 0:
            raise ValueError("could not partition Jenks input into the requested classes")
        boundaries.append(values[end - 1])
        end = start
    return list(reversed(boundaries))


def fisher_jenks_breaks(values: list[float], class_count: int) -> list[float]:
    """Compute optimal one-dimensional Fisher–Jenks upper bounds by dynamic programming."""
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        raise ValueError("Jenks input must contain at least one value")
    if class_count < 1 or class_count > len(set(sorted_values)):
        raise ValueError("class_count must be between 1 and the number of unique values")
    splits = _find_jenks_splits(sorted_values, class_count)
    return _recover_jenks_breaks(sorted_values, class_count, splits)


def _jenks_assignments(
    fixture: Path,
    id_field: str,
    value_field: str,
    class_count: int,
) -> tuple[list[float], dict[str, int]]:
    features = _features(fixture)
    values: list[tuple[str, float]] = []
    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("each input feature must have a properties object")
        identifier = properties.get(id_field)
        value = properties.get(value_field)
        if (
            not isinstance(identifier, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise ValueError(f"feature requires string {id_field} and numeric {value_field}")
        values.append((identifier, float(value)))
    if len({identifier for identifier, _ in values}) != len(values):
        raise ValueError(f"input {id_field} values must be unique")
    breaks = fisher_jenks_breaks([value for _, value in values], class_count)
    assignments = {
        identifier: next(index for index, upper in enumerate(breaks, start=1) if value <= upper)
        for identifier, value in values
    }
    return breaks, assignments


def _evaluate_feature_count(assertion: dict[str, object], output_path: Path) -> AssertionResult:
    assertion_id = str(assertion.get("id", "<unnamed>"))
    features = _features(output_path)
    expected = assertion.get("expected")
    return AssertionResult(
        assertion_id,
        len(features) == expected,
        f"feature count {len(features)}; expected {expected}",
    )


def _representative_point_reference(
    assertion: dict[str, object], task_root: Path
) -> tuple[dict[str, object], object, str]:
    fixture_path = _safe_path(task_root, str(assertion["fixture"]))
    id_field = str(assertion["id_field"])
    feature_id = str(assertion["feature_id"])
    matches = [
        feature
        for feature in _features(fixture_path)
        if feature.get("properties", {}).get(id_field) == feature_id
    ]
    if len(matches) != 1:
        raise ValueError(f"fixture must contain exactly one feature with {id_field}={feature_id}")
    source_feature = matches[0]
    expected_point = shape(source_feature["geometry"]).representative_point()
    return source_feature, expected_point, id_field


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
    for field in preserve_fields:
        if output_properties.get(field) != source_properties.get(field):
            return AssertionResult(
                assertion_id,
                False,
                f"output feature must preserve {field}={source_properties.get(field)!r}",
            )
    output_geometry = output_feature.get("geometry")
    if not isinstance(output_geometry, dict) or output_geometry.get("type") != "Point":
        return AssertionResult(assertion_id, False, "output geometry must be a GeoJSON Point")
    coordinates = output_geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return AssertionResult(
            assertion_id, False, "output point must have [longitude, latitude] coordinates"
        )
    return None


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


def _evaluate_representative_point(
    assertion: dict[str, object], task_root: Path, output_path: Path
) -> AssertionResult:
    assertion_id = str(assertion.get("id", "<unnamed>"))
    source_feature, expected_point, id_field = _representative_point_reference(assertion, task_root)
    output_features = _features(output_path)
    preserve_fields = assertion.get("preserve_fields", [id_field])
    issue = _point_output_issue(assertion_id, output_features, source_feature, preserve_fields)
    if issue is not None:
        return issue
    coordinates = output_features[0]["geometry"]["coordinates"]
    tolerance = float(assertion.get("tolerance_degrees", 0.0))
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
    fixture_path = _safe_path(task_root, str(assertion["fixture"]))
    id_field = str(assertion["id_field"])
    by_id = {
        feature.get("properties", {}).get(id_field): feature for feature in _features(fixture_path)
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


def _evaluate_de9im(
    assertion: dict[str, object], task_root: Path, output_path: Path
) -> AssertionResult:
    assertion_id = str(assertion.get("id", "<unnamed>"))
    left, right = _load_relation_geometries(assertion, task_root)
    matrix, actual_relation = _de9im_relation(left, right, str(assertion["expected_relation"]))
    expected_matrix = str(assertion["expected_matrix"])
    if matrix != expected_matrix:
        return AssertionResult(
            assertion_id,
            False,
            f"fixture relation matrix is {matrix}; expected {expected_matrix}",
        )
    submitted = _read_json(output_path)
    return _relation_result(assertion_id, submitted, matrix, actual_relation)


def _relation_result(
    assertion_id: str,
    submitted: dict[str, object],
    matrix: str,
    relation: str,
) -> AssertionResult:
    passed = (
        set(submitted) == {"relation", "de9im"}
        and submitted.get("de9im") == matrix
        and submitted.get("relation") == relation
    )
    message = (
        f"submitted relation={submitted.get('relation')!r}, "
        f"de9im={submitted.get('de9im')!r}; expected relation={relation!r}, "
        f"de9im={matrix!r}"
    )
    return AssertionResult(assertion_id, passed, message)


def _evaluate_jenks(
    assertion: dict[str, object], task_root: Path, output_path: Path
) -> AssertionResult:
    assertion_id = str(assertion.get("id", "<unnamed>"))
    fixture_path = _safe_path(task_root, str(assertion["fixture"]))
    breaks, assignments = _jenks_assignments(
        fixture_path,
        str(assertion["id_field"]),
        str(assertion["value_field"]),
        int(assertion["class_count"]),
    )
    submitted = _read_json(output_path)
    passed = (
        set(submitted) == {"method", "class_count", "breaks", "assignments"}
        and submitted.get("method") == "jenks"
        and submitted.get("class_count") == len(breaks)
        and submitted.get("breaks") == breaks
        and submitted.get("assignments") == assignments
    )
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
    output_path = _safe_path(artifact_root, str(assertion.get("output", "")))
    handlers = {
        "geojson_feature_count": lambda: _evaluate_feature_count(assertion, output_path),
        "representative_point_matches": lambda: _evaluate_representative_point(
            assertion, task_root, output_path
        ),
        "de9im_relation": lambda: _evaluate_de9im(assertion, task_root, output_path),
        "jenks_classification": lambda: _evaluate_jenks(assertion, task_root, output_path),
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


RunFingerprint = tuple[bool, tuple[tuple[str, bool, str], ...]]
GatePass = tuple[dict[str, object], RunFingerprint | None, str | None]


def _gate_run_result(
    run_number: int,
    task_path: Path,
    artifact_root: Path,
    evaluator: Callable[[Path, Path], OracleVerdict | None],
) -> GatePass:
    try:
        verdict = evaluator(task_path, artifact_root)
    except Exception as exc:  # Keep later passes running after a recorded failure.
        message = f"{type(exc).__name__}: {exc}"
        result = {"run": run_number, "status": "error", "error": message}
        return result, None, f"run {run_number} errored: {message}"
    if verdict is None:
        message = "oracle produced no verdict"
        result = {"run": run_number, "status": "missing", "error": message}
        return result, None, f"run {run_number} is missing a verdict"
    result = {
        "run": run_number,
        "status": "passed" if verdict.passed else "failed",
        "verdict": verdict.to_dict(),
    }
    issue = None if verdict.passed else f"run {run_number} failed one or more oracle assertions"
    return result, verdict.fingerprint(), issue


def _gate_fingerprints_match(fingerprints: list[RunFingerprint | None], required_runs: int) -> bool:
    present = [fingerprint for fingerprint in fingerprints if fingerprint is not None]
    return len(present) == required_runs and len(set(present)) == 1


def _load_gate_task(task_path: Path) -> tuple[dict[str, object] | None, str | None]:
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        return None, "task YAML must contain a mapping"
    oracle = task.get("oracle", {})
    required_runs = oracle.get("determinism_runs") if isinstance(oracle, dict) else None
    if type(required_runs) is not int or required_runs != 3:
        return None, f"schema requires exactly 3 determinism runs; found {required_runs!r}"
    return task, None


def run_determinism_gate(
    task_path: Path,
    artifact_root: Path,
    evaluator: Callable[[Path, Path], OracleVerdict | None] = evaluate_task,
) -> DeterminismReport:
    """Run the oracle three times and fail on missing or inconsistent verdicts."""
    task_path = task_path.resolve()
    task, task_issue = _load_gate_task(task_path)
    if task_issue is not None:
        return DeterminismReport(False, 3, False, (), (task_issue,))

    results: list[dict[str, object]] = []
    fingerprints: list[RunFingerprint | None] = []
    issues: list[str] = []
    for run_number in range(1, 4):
        result, fingerprint, issue = _gate_run_result(
            run_number, task_path, artifact_root, evaluator
        )
        results.append(result)
        fingerprints.append(fingerprint)
        if issue is not None:
            issues.append(issue)
    consistent = _gate_fingerprints_match(fingerprints, 3)
    if not consistent:
        issues.append("oracle verdicts are missing or inconsistent across the three runs")
    passed = consistent and all(result.get("status") == "passed" for result in results)
    return DeterminismReport(passed, 3, consistent, tuple(results), tuple(issues))
