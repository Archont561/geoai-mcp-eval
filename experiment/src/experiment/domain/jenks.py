"""Pure domain validation for Fisher–Jenks natural-breaks classification.

The numerical classifier itself lives in :mod:`experiment.adapters.jenks`
(backed by ``mapclassify.FisherJenks``) so ``experiment.domain`` remains 100%
pure Python with zero NumPy or SciPy dependencies.
"""

from __future__ import annotations

from collections.abc import Sequence


def validate_jenks_inputs(values: Sequence[float], class_count: int) -> list[float]:
    """Validate and sort Fisher–Jenks inputs, returning ascending floats."""
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        raise ValueError("Jenks input must contain at least one value")
    if class_count < 1 or class_count > len(set(sorted_values)):
        raise ValueError("class_count must be between 1 and the number of unique values")
    return sorted_values
