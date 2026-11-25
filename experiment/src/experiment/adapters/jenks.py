"""Fisher–Jenks natural breaks backed by ``jenkspy.jenks_breaks`` (GEO-028)."""

from __future__ import annotations

from collections.abc import Sequence

import jenkspy

from experiment.domain.jenks import validate_jenks_inputs


def fisher_jenks_breaks(values: Sequence[float], class_count: int) -> list[float]:
    """Compute optimal one-dimensional Fisher–Jenks upper bounds via ``jenkspy``."""
    sorted_values = validate_jenks_inputs(values, class_count)
    if class_count == 1:
        return [sorted_values[-1]]
    unique = sorted(set(sorted_values))
    if class_count == len(unique):
        return unique
    # jenkspy returns k + 1 inclusive bounds [min, b_1, ..., b_k]; drop leading min.
    bounds = jenkspy.jenks_breaks(sorted_values, n_classes=class_count)
    return [float(upper) for upper in bounds[1:]]
