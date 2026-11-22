"""Shared result types and safe file helpers for the pilot oracle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


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


def safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError("oracle paths must be relative")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("oracle path escapes its allowed directory")
    return resolved


def read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object or GeoJSON object")
    return data


def geojson_features(path: Path) -> list[dict[str, object]]:
    data = read_json(path)
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("expected a GeoJSON FeatureCollection")
    features = data["features"]
    if not all(isinstance(feature, dict) for feature in features):
        raise ValueError("each GeoJSON feature must be an object")
    return features
