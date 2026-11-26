"""Properties of trial measurement options."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.measurement import TrialMeasurementOptions


@given(seconds=st.floats(max_value=-0.0001, allow_nan=False, allow_infinity=False))
def test_negative_wall_time_is_rejected(seconds: float) -> None:
    with pytest.raises(ValidationError):
        TrialMeasurementOptions(wall_seconds=seconds)
